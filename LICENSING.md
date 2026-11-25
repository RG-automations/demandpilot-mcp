# Licensing

DemandPilot MCP uses a **dual-licensing model** for its own source code:

1. **Open Source — GNU Affero General Public License v3.0 (`AGPL-3.0-only`)**, available to
   everyone, at no cost, under the terms in [`LICENSE`](LICENSE) (the complete, unmodified
   official text from the Free Software Foundation).
2. **Commercial License** - a separate, individually negotiated license, available from the
   copyright holder for organizations that need terms the AGPL does not provide. See
   [`COMMERCIAL_LICENSE.md`](COMMERCIAL_LICENSE.md).

This is the same model used by a number of open-source infrastructure projects: the public
version is fully functional, genuinely open source, and usable - including commercially - under
AGPL terms; a commercial license is an *alternative*, not a requirement, for most users.

## Why AGPL and not a permissive license

The AGPL was chosen specifically for its network-use clause (AGPL section 13): unlike the plain
GPL, it also covers the case where a modified version is operated as a network service that
other people interact with remotely, without ever being "distributed" in the traditional sense.
Since an MCP server is exactly this kind of long-running service accessed by a client, this
closes a loophole the GPL does not. See "What AGPL actually requires" below for what this does
*not* mean in practice.

## What AGPL actually requires (and what it doesn't)

| Scenario | AGPL obligation |
|---|---|
| You run DemandPilot MCP yourself, locally, for your own use | **None.** Running software you were given is not "distribution"; you owe nothing to anyone. |
| You connect to it from an MCP client (Claude Desktop, Claude Code, or your own agent) over stdio | **None on the client.** Interacting with a program through its normal interface is not "conveying" a copy of that program. Your client code does not become AGPL-licensed, and you do not have to open-source your client. |
| You redistribute DemandPilot MCP's source code, unmodified | Keep the copyright and license notices; make the same AGPL terms available to recipients. |
| You redistribute a **modified** version of DemandPilot MCP's source code | Same as above, plus: mark what you changed, and license your modified version under AGPL-3.0 too. |
| You run a **modified** version of DemandPilot MCP as a network-accessible service that remote users interact with | You must offer those remote users the Corresponding Source of your modified version (AGPL section 13) - this is the clause that does not exist in the plain GPL. |
| You want to do any of the above *without* these AGPL obligations (e.g. ship it inside closed-source software, or run a modified SaaS version without publishing your changes) | That needs a **commercial license** - see below. |

**What AGPL does *not* say**: it does not say every company that merely *uses* DemandPilot MCP,
or connects a client to it, must buy a commercial license or release its own source code. Those
obligations attach to *conveying* (distributing) the covered work or a modified version of it,
and to operating a modified version as a remote network service - not to ordinary use.

This summary is provided for orientation and is not legal advice; the authoritative text is the
AGPL-3.0 license itself (<https://www.gnu.org/licenses/agpl-3.0.html>) and the FSF's GPL FAQ
(<https://www.gnu.org/licenses/gpl-faq.html>).

## Future commercialization (direction only, not implemented)

Preserving the ability to offer a commercial license is a deliberate business decision behind
this structure. Possible future directions - **none of which are implemented in this MVP** -
include: paid support, custom/on-premise deployments, ERP integrations, proprietary extensions,
a hosted MCP server, and a future SaaS offering. None of these require, and none currently
involve, payments, license keys, activation, DRM, user accounts, authentication, telemetry, or
any mechanism that restricts the open-source version - adding any of those now would be outside
this project's locked MVP scope.

## Third-party components

DemandPilot MCP's own code is AGPL-3.0-only. Its dependencies keep their own (permissive)
licenses - see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the full audit. Using a
permissively-licensed dependency does not place that dependency's code under AGPL, and nothing
here changes those projects' own licensing.

## Contributions

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for how external contributions are intended to be
handled, including why a Contributor License Agreement (CLA) is anticipated before the project
accepts external pull requests.
