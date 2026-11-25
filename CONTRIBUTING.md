# Contributing

Thank you for your interest in DemandPilot MCP. This document describes the intended process for
future external contributions. **No external contributions are being accepted yet** - this is a
statement of direction for when the project is published, not an active process today.

## Scope

Contributions should stay within the project's locked MVP scope (see `SPECIFICATION.md`): five
MCP tools, one resource, one prompt, SQLite, Holt-Winters/Seasonal Naive forecasting, the
official MCP SDK, stdio transport, synthetic data only, a minimal dependency set. Proposals that
add new transports (HTTP/REST), new databases, new forecasting libraries, cloud services, user
accounts/auth, or other technology explicitly excluded in `SPECIFICATION.md` section 17 will not
be accepted without a separate, explicit decision to change scope.

## Why a CLA is anticipated

This project uses a dual-licensing model (see [`LICENSING.md`](LICENSING.md)): the public code is
AGPL-3.0-only, and the copyright holder also intends to retain the ability to offer the same code
under a separate commercial license. That second part only works if the copyright holder either
holds, or has been granted sufficient rights over, the *entire* codebase - including any code
contributed by other people.

**Simply accepting a pull request, or relying on a Developer Certificate of Origin (DCO), does
not by itself give the project the right to relicense a contributor's code under different
terms.** A DCO confirms a contributor had the right to submit their contribution under the
project's current license; it does not grant the additional right to relicense that contribution
commercially. For that, a **Contributor License Agreement (CLA)** - a separate agreement in which
a contributor grants the project maintainer the necessary rights (typically a license broad
enough to cover both the AGPL distribution and any future commercial licensing) - is the standard
mechanism.

**No binding CLA exists yet.** Before this project accepts external contributions in a way that
must support future commercial (re)licensing, a CLA will need to be drafted and reviewed by a
qualified lawyer. This document only records that requirement; it does not create one.

## In the meantime

- Bug reports and suggestions are welcome as issues once the project is published, but will be
  triaged by the maintainer; there is no commitment to accept code changes before a CLA process
  exists.
- Any code accepted before a CLA is in place would need its licensing status resolved
  individually with that contributor.

## Code of conduct

A formal code of conduct has not been adopted yet. Basic expectations: be respectful, assume good
faith, and keep discussion focused on the project.
