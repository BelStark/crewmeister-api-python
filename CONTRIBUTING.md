# Contributing

Everyone is welcome to propose changes to the Crewmeister SDK, CLI, MCP server
and companion consumer integration. [BelStark](https://github.com/BelStark) is
the primary maintainer and decides which contributions and releases are accepted.
Submitting a contribution does not grant repository write or release access.
Independent forks remain permitted under the license.

## Contribution terms

Submit contributions under [Apache-2.0](LICENSE). Contributors retain their
copyright; no copyright assignment or separate CLA is required. Identify any
third-party material, its source and license, and preserve its required notices.
Do not submit material you lack permission to distribute.

Certify the [Developer Certificate of Origin 1.1](DCO) for each contributed
commit with a `Signed-off-by` trailer, normally added using `git commit --signoff`.
Only sign off when you can make that certification. The name and email in the
trailer become part of the public commit history; a sign-off is not a
cryptographic signature. The maintainer checks sign-offs before merging.

## Pull requests

- Keep changes focused and explain the behavior and validation performed.
- Follow the [README's offline validation instructions](README.md#mandatory-offline-validation).
- Use synthetic test data. Never include credentials, employee data or internal
  API captures, and never run tests against live Crewmeister accounts.
- Report security issues privately through the repository's private vulnerability
  reporting feature when available; never put sensitive details in a public issue.

Participation and support are voluntary. No support response time, maintenance
period or release schedule is promised. The warranty and liability provisions
of Apache-2.0 apply subject to applicable law; these guidelines add no license
restrictions.
