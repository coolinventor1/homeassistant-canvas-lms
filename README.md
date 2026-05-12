# Canvas LMS for Home Assistant

`canvas_lms` is a HACS-ready custom integration for Home Assistant that connects to Canvas and exposes assignment and course data as sensors.

New installations use Canvas OAuth so you do not need a manually created personal access token. Existing token-based installs can continue working.

## What it exposes

- `Next assignment due`
- `Upcoming assignments`
- `Assignments due today`
- `Missing assignments`
- `Courses tracked`
- `Assignments needing grading`

The sensors include useful attributes such as assignment titles, due dates, course names, current grades when Canvas exposes them, and per-course workload summaries.

## Installation

### HACS custom repository

1. In HACS, add `https://github.com/coolinventor1/homeassistant-canvas-lms` as a custom repository with category `Integration`.
2. Install `Canvas LMS`.
3. Restart Home Assistant.

### Manual install

1. Copy `custom_components/canvas_lms` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## Configuration

Add the integration from **Settings -> Devices & services -> Add integration** and search for `Canvas LMS`.

You will need:

- Your Canvas base URL, for example `https://school.instructure.com`
- A Canvas OAuth client ID and client secret from a Canvas Developer Key

## Canvas OAuth setup

Ask your Canvas admin to create or enable a Canvas API Developer Key for this integration.

They should configure:

- A redirect URI matching the value Home Assistant shows during setup
- Usually this is `https://<your-home-assistant>/auth/external/callback`
- If your Home Assistant instance uses My Home Assistant for OAuth redirects, use the exact redirect URI shown in the setup form instead

If the Developer Key is scoped, ask them to allow these scopes:

- `url:GET|/api/v1/users/self/profile`
- `url:GET|/api/v1/courses`
- `url:GET|/api/v1/calendar_events`
- `url:GET|/api/v1/users/self/missing_submissions`

If the Developer Key is scoped, ask them to enable `Allow Include Parameters` as well. This integration relies on Canvas `include[]` query parameters for course details such as teachers and grading summaries.

## Notes

- The integration polls Canvas on a configurable interval. The default is every 15 minutes.
- Upcoming assignment tracking defaults to a 14-day window.
- Canvas access tokens issued through OAuth expire quickly, so the integration stores the refresh token and renews access automatically.
