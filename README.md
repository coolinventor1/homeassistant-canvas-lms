# Canvas LMS for Home Assistant

`canvas_lms` is a HACS-ready custom integration for Home Assistant that connects to Canvas and exposes assignment and course data as sensors.

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

1. Push this repository to GitHub.
2. In HACS, add it as a custom repository with category `Integration`.
3. Install `Canvas LMS`.
4. Restart Home Assistant.

### Manual install

1. Copy `custom_components/canvas_lms` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## Configuration

Add the integration from **Settings -> Devices & services -> Add integration** and search for `Canvas LMS`.

You will need:

- Your Canvas base URL, for example `https://school.instructure.com`
- A Canvas API token from your Canvas account settings

## Notes

- The integration polls Canvas on a configurable interval. The default is every 15 minutes.
- Upcoming assignment tracking defaults to a 14-day window.
- If you publish this repo, update the placeholder GitHub URLs in `custom_components/canvas_lms/manifest.json`.

