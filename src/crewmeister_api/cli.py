"""Command-line helpers for Crewmeister API access."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from importlib.metadata import version
from typing import Any, BinaryIO, Never, TextIO, cast

from crewmeister_api.catalog import describe_api
from crewmeister_api.categories import API_CATEGORIES, ApiCategorySpec
from crewmeister_api.client import (
    CrewmeisterApiClient,
    CrewmeisterApiConfig,
    CrewmeisterApiError,
    CrewmeisterAuthenticationError,
    CrewmeisterConfigError,
    CrewmeisterTransportError,
    JsonValue,
    QueryValue,
)
from crewmeister_api.configuration import load_env_file
from crewmeister_api.safe_output import redact_sensitive, structured_error

ClientFactory = Callable[[], CrewmeisterApiClient]

WRITE_OPERATIONS = {"create", "batch", "patch", "replace", "delete", "task"}
BINARY_DOWNLOAD_RESOURCES = frozenset({("time-tracking", "time-tracking-reports"), ("salary-export", "salary-exports")})


class CliParseExit(RuntimeError):
    """Raised when argparse wants to exit."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(str(status))


class CliArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that routes help and errors through injected streams."""

    def __init__(self, *args: Any, stdout: TextIO, stderr: TextIO, error_format: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._stdout = stdout
        self._stderr = stderr
        self._error_format = error_format

    def exit(self, status: int = 0, message: str | None = None) -> Never:
        if message:
            self._stderr.write(message)
        raise CliParseExit(status)

    def error(self, message: str) -> Never:
        if self._error_format == "json":
            raise CliParseExit(2)
        self.print_usage(self._stderr)
        self.exit(2, f"{self.prog}: error: {message}\n")

    def print_help(self, file: Any = None) -> None:
        super().print_help(file or self._stdout)

    def print_usage(self, file: Any = None) -> None:
        super().print_usage(file or self._stderr)

    def _print_message(self, message: str | None, file: Any = None) -> None:
        if message:
            target = self._stdout if file is sys.stdout else (file or self._stderr)
            target.write(message)


def run_cli(
    argv: Sequence[str],
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    stdin: TextIO | None = None,
    client_factory: ClientFactory | None = None,
) -> int:
    """Run the Crewmeister command-line interface."""

    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    stdin = sys.stdin if stdin is None else stdin
    error_format = _requested_error_format(argv)
    parser = _parser(stdout=stdout, stderr=stderr, error_format=error_format)
    try:
        namespace = parser.parse_args(_normalize_sort_args(argv) if argv else ["--help"])
        error_format = namespace.error_format
        if getattr(namespace, "describe", False):
            json.dump(describe_api(namespace.describe_category, namespace.describe_endpoint), stdout, sort_keys=True)
            stdout.write("\n")
            return 0
        if namespace.operation in WRITE_OPERATIONS and not namespace.yes:
            if error_format == "json":
                _write_structured_error(stderr, {"type": "confirmation", "message": "Write confirmation required."})
            else:
                stderr.write("Refusing to run write command without --yes.\n")
            return 2
        factory = client_factory or (lambda: _client_from_env(namespace.env_file))
        return _execute(namespace, factory, stdout=stdout, stderr=stderr, stdin=stdin)
    except CliParseExit as exc:
        if error_format == "json" and exc.status:
            _write_structured_error(stderr, {"type": "syntax", "message": "Syntax error."})
        return exc.status
    except (
        CrewmeisterApiError,
        CrewmeisterAuthenticationError,
        CrewmeisterConfigError,
        CrewmeisterTransportError,
    ) as exc:
        _write_error(stderr, exc, error_format)
        return 1
    except OSError as exc:
        _write_error(stderr, exc, error_format)
        return 1
    except ValueError as exc:
        _write_error(stderr, exc, error_format)
        return 2


def _parser(*, stdout: TextIO, stderr: TextIO, error_format: str) -> argparse.ArgumentParser:
    class Parser(CliArgumentParser):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, stdout=stdout, stderr=stderr, error_format=error_format, **kwargs)

    parser = Parser(prog="crewmeister", description="Crewmeister API SDK command-line client")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('crewmeister-api')}")
    parser.add_argument(
        "--env-file", metavar="PATH", help="load a UTF-8 .env file; environment variables take precedence"
    )
    parser.add_argument("--error-format", choices=("text", "json"), default="text")
    categories = parser.add_subparsers(dest="category_name", required=True, parser_class=Parser)
    describe_parser = categories.add_parser("describe", help="write an offline machine-readable API catalog as JSON")
    describe_parser.set_defaults(describe=True)
    describe_parser.add_argument("describe_category", nargs="?")
    describe_parser.add_argument("describe_endpoint", nargs="?")
    describe_parser.add_argument("--json", action="store_true", help="write JSON (the only supported format)")
    for name, category in API_CATEGORIES.items():
        category_parser = categories.add_parser(name, help=category.display_name)
        category_parser.set_defaults(category=category)
        resources = category_parser.add_subparsers(dest="resource_name", required=True, parser_class=Parser)
        for resource_name, endpoint in category.resources.items():
            resource_parser = resources.add_parser(resource_name)
            operations = resource_parser.add_subparsers(dest="operation", required=True, parser_class=Parser)
            for operation in sorted(endpoint.supported_operations):
                _add_resource_options(operations.add_parser(operation), operation)
            if (name, resource_name) in BINARY_DOWNLOAD_RESOURCES:
                _add_resource_options(operations.add_parser("download"), "download")
            _add_resource_options(operations.add_parser("job"), "job")
        if category.tasks:
            task_parser = resources.add_parser("task")
            tasks = task_parser.add_subparsers(dest="task_name", required=True, parser_class=Parser)
            for task_name in category.tasks:
                operation_parser = tasks.add_parser(task_name)
                operation_parser.set_defaults(operation="task")
                _add_task_options(
                    operation_parser, i_cal_export=name == "integration" and task_name == "i-cal-subscription"
                )
            job_parser = resources.add_parser("job", help="read a job for a registered task")
            job_parser.set_defaults(operation="task-job")
            job_parser.add_argument("task_name", choices=category.tasks)
            job_parser.add_argument("job_id")
    return parser


def _execute(
    namespace: argparse.Namespace, factory: ClientFactory, *, stdout: TextIO, stderr: TextIO, stdin: TextIO
) -> int:
    category: ApiCategorySpec = namespace.category
    resource_name = namespace.resource_name
    operation = namespace.operation
    query = _build_query(namespace)
    output_file = getattr(namespace, "output_file", None)
    if output_file is not None and getattr(namespace, "async_write", False):
        raise ValueError("--async cannot be combined with --output-file.")
    if operation == "list":
        if namespace.page is not None and namespace.limit is not None:
            raise ValueError("--page and --limit cannot be combined.")
        if {"page", "pageSize"} & query.keys():
            raise ValueError("page and pageSize are reserved; use --page and --page-size.")
    service = category.service_type(factory())
    if operation == "list":
        if namespace.page is not None:
            _write_json(
                service.get_resource_page(
                    resource_name, page=namespace.page, query=query, page_size=namespace.page_size
                ),
                stdout,
                sensitive_exact_keys=category.sensitive_exact_keys,
            )
            return 0
        items = service.iter_resource(
            resource_name,
            query=query,
            page_size=namespace.page_size,
            limit=namespace.limit,
        )
        _write_json_array(items, stdout, sensitive_exact_keys=category.sensitive_exact_keys)
        return 0
    if operation == "download":
        with _exclusive_output_file(namespace.output_file, binary=True) as output:
            service.download_resource(resource_name, namespace.item_id, cast(BinaryIO, output), query=query)
        return 0
    payload: JsonValue
    if output_file is not None:
        with _exclusive_output_file(output_file) as output:
            payload = service.run_task(
                namespace.task_name,
                _read_json(namespace.json_file, stdin),
                query=query,
                async_write=namespace.async_write,
            )
            _write_i_cal_feed(cast(TextIO, output), payload)
    elif operation == "task":
        payload = service.run_task(
            namespace.task_name,
            _read_json(namespace.json_file, stdin),
            query=query,
            async_write=namespace.async_write,
        )
    elif operation == "task-job":
        payload = service.get_task_job(namespace.task_name, namespace.job_id)
    elif operation == "job":
        payload = service.get_resource_job(resource_name, namespace.job_id)
    elif operation == "get":
        payload = service.get_resource(resource_name, namespace.item_id, query=query)
    elif operation == "create":
        payload = service.create_resource(
            resource_name,
            _read_json(namespace.json_file, stdin),
            query=query,
            async_write=namespace.async_write,
        )
    elif operation == "batch":
        payload = service.batch_patch_resource(
            resource_name,
            _read_json(namespace.json_file, stdin),
            query=query,
            async_write=namespace.async_write,
        )
    elif operation == "patch":
        payload = service.patch_resource(
            resource_name,
            namespace.item_id,
            _read_json(namespace.json_file, stdin),
            query=query,
            async_write=namespace.async_write,
        )
    elif operation == "replace":
        payload = service.replace_resource(
            resource_name,
            namespace.item_id,
            _read_json(namespace.json_file, stdin),
            query=query,
            async_write=namespace.async_write,
        )
    else:
        payload = service.delete_resource(
            resource_name, namespace.item_id, query=query, async_write=namespace.async_write
        )
    _write_json(payload, stdout, sensitive_exact_keys=category.sensitive_exact_keys)
    if operation in {"job", "task-job"} and _job_status(payload) == "ERROR":
        if namespace.error_format == "json":
            _write_structured_error(stderr, {"type": "job", "message": "Crewmeister job reported ERROR."})
        else:
            stderr.write("Crewmeister job reported ERROR.\n")
        return 1
    return 0


def _add_resource_options(parser: argparse.ArgumentParser, operation: str) -> None:
    if operation == "job":
        parser.add_argument("job_id")
        return
    _add_query_options(parser)
    if operation == "list":
        parser.add_argument("--page", type=_non_negative_int, default=None, help="return one raw page with metadata")
        parser.add_argument("--page-size", type=_non_zero_positive_int, default=None)
        parser.add_argument("--limit", type=_non_negative_int, default=None)
        return
    if operation in {"get", "delete", "download"}:
        parser.add_argument("item_id")
    if operation == "download":
        parser.add_argument("--output-file", required=True, metavar="PATH")
    if operation in {"create", "batch"}:
        _add_json_payload_options(parser)
    if operation in {"patch", "replace"}:
        parser.add_argument("item_id")
        _add_json_payload_options(parser)
    if operation in WRITE_OPERATIONS:
        parser.add_argument("--yes", action="store_true", help="confirm the write operation")
        parser.add_argument("--async", dest="async_write", action="store_true", help="request asynchronous processing")
    return


def _add_task_options(parser: argparse.ArgumentParser, *, i_cal_export: bool = False) -> None:
    _add_query_options(parser)
    _add_json_payload_options(parser)
    parser.add_argument("--yes", action="store_true", help="confirm the task operation")
    parser.add_argument("--async", dest="async_write", action="store_true", help="request asynchronous processing")
    if i_cal_export:
        parser.add_argument("--output-file", metavar="PATH", help="write the iCal feed to a new file")


def _add_query_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--filter", dest="filter_value", default=None)
    parser.add_argument("--sort", action="append", default=[])
    parser.add_argument("--query", action="append", default=[], type=_query_pair, metavar="KEY=VALUE")


def _add_json_payload_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json-file", required=True, help="JSON payload path, or '-' for stdin")


def _build_query(namespace: argparse.Namespace) -> dict[str, QueryValue]:
    query: dict[str, str | list[str]] = {}
    if (filter_value := getattr(namespace, "filter_value", None)) is not None:
        query["filter"] = filter_value
    if sort := getattr(namespace, "sort", []):
        query["sort"] = list(sort)
    for key, value in getattr(namespace, "query", []):
        existing = query.get(key)
        if existing is None:
            query[key] = value
        elif isinstance(existing, list):
            existing.append(value)
        else:
            query[key] = [existing, value]
    return dict(query)


def _query_pair(value: str) -> tuple[str, str]:
    key, separator, raw_value = value.partition("=")
    if not separator or not key:
        raise argparse.ArgumentTypeError("--query values must use KEY=VALUE.")
    return key, raw_value


def _normalize_sort_args(args: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--sort" and index + 1 < len(args) and not args[index + 1].startswith("--"):
            normalized.append(f"--sort={args[index + 1]}")
            index += 2
        else:
            normalized.append(arg)
            index += 1
    return normalized


def _non_zero_positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be greater than or equal to zero")
    return parsed


def _read_json(path: str, stdin: TextIO) -> JsonValue:
    if path == "-":
        text = stdin.read()
    else:
        with open(path, encoding="utf-8") as payload_file:
            text = payload_file.read()
    try:
        return cast(JsonValue, json.loads(text))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} did not contain valid JSON.") from exc


def _job_status(payload: JsonValue) -> str | None:
    status = payload.get("status") if isinstance(payload, dict) else None
    return status if isinstance(status, str) else None


@contextmanager
def _exclusive_output_file(path: str, *, binary: bool = False) -> Iterator[TextIO | BinaryIO]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ValueError("Output file could not be prepared.") from exc
    created = os.fstat(descriptor)
    try:
        os.fchmod(descriptor, 0o600)
        output = os.fdopen(descriptor, "wb") if binary else os.fdopen(descriptor, "w", encoding="utf-8")
    except OSError as exc:
        os.close(descriptor)
        _remove_owned_file(path, created)
        raise ValueError("Output file could not be prepared.") from exc
    complete = False
    try:
        yield output
        if output.tell():
            output.flush()
            os.fsync(output.fileno())
            complete = True
    finally:
        try:
            output.close()
        finally:
            if not complete:
                _remove_owned_file(path, created)


def _remove_owned_file(path: str, created: os.stat_result) -> None:
    try:
        current = os.stat(path, follow_symlinks=False)
        if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
            os.unlink(path)
    except OSError:
        pass


def _write_i_cal_feed(output: TextIO, payload: JsonValue) -> None:
    resource_after_write = payload.get("resourceAfterWrite") if isinstance(payload, dict) else None
    task_output = resource_after_write.get("output") if isinstance(resource_after_write, dict) else None
    feed_url = task_output.get("feedURL") if isinstance(task_output, dict) else None
    if not isinstance(feed_url, str) or not feed_url:
        raise ValueError("Crewmeister result did not include an iCal feed URL.")
    output.write(feed_url)


def _write_json_array(items: Iterator[JsonValue], stdout: TextIO, *, sensitive_exact_keys: frozenset[str]) -> None:
    try:
        first = next(items)
    except StopIteration:
        stdout.write("[]\n")
        return
    stdout.write("[")
    _write_json(first, stdout, sensitive_exact_keys=sensitive_exact_keys)
    del first
    stdout.flush()
    for item in items:
        stdout.write(",")
        _write_json(item, stdout, sensitive_exact_keys=sensitive_exact_keys)
        stdout.flush()
    stdout.write("]\n")


def _write_json(payload: JsonValue, stdout: TextIO, *, sensitive_exact_keys: frozenset[str] = frozenset()) -> None:
    stdout.write(
        json.dumps(
            redact_sensitive(payload, sensitive_exact_keys=sensitive_exact_keys),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    stdout.write("\n")


def _client_from_env(env_file: str | None = None) -> CrewmeisterApiClient:
    if env_file is None:
        return CrewmeisterApiClient(CrewmeisterApiConfig.from_env())
    return CrewmeisterApiClient(CrewmeisterApiConfig.from_env(load_env_file(env_file)))


def _format_error(exc: Exception) -> str:
    if isinstance(exc, CrewmeisterApiError):
        details = [f"HTTP {exc.status_code}"]
        if exc.code:
            details.append(f"code={exc.code}")
        if exc.request_id:
            details.append(f"request_id={exc.request_id}")
        return "Crewmeister API error: " + " ".join(details)
    return str(exc)


def _requested_error_format(argv: Sequence[str]) -> str:
    error_format = "text"
    for index, argument in enumerate(argv):
        option, separator, value = argument.partition("=")
        if len(option) > 2 and "--error-format".startswith(option):
            error_format = value if separator else (argv[index + 1] if index + 1 < len(argv) else "")
    return error_format if error_format in {"text", "json"} else "text"


def _write_error(stderr: TextIO, exc: Exception, error_format: str) -> None:
    if error_format == "json":
        _write_structured_error(stderr, structured_error(exc))
    elif isinstance(exc, OSError):
        stderr.write(f"I/O error: {exc}\n")
    elif isinstance(exc, ValueError) and not isinstance(exc, CrewmeisterConfigError):
        stderr.write(f"Input error: {exc}\n")
    else:
        stderr.write(f"{_format_error(exc)}\n")


def _write_structured_error(stderr: TextIO, error: dict[str, str | int]) -> None:
    json.dump({"error": error}, stderr, sort_keys=True)
    stderr.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(sys.argv[1:] if argv is None else argv)
