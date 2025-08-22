# Grow A Garden Stock - Live Update (Clone)

A minimal clone of the Gamersberg Grow A Garden stock page with live updates using Server-Sent Events (SSE). It uses a public GitHub repository API as a placeholder data source to simulate stock changes.

## Features

- Live updates via SSE at `/api/stock/stream`
- Initial REST fetch at `/api/stock`
- Static client in `public/` rendering stock items
- Uses GitHub API as a mock data source (can be swapped)

## Requirements

- Node.js 18+

## Install

```bash
cd /workspace/gag-stock-clone
npm install
```

## Run

```bash
npm start
```

- Server will start on `http://localhost:3000/`
- Open `http://localhost:3000/` in your browser to see updates.

## Endpoints

- `GET /api/stock` returns current simulated stock snapshot
- `GET /api/stock/stream` streams updates every 10s (SSE)

## Swap Data Source

By default, the server uses `https://api.github.com/repos/vercel/next.js` to derive pseudo-random stock booleans. To use another public GitHub repository as the data source, change the URL inside `fetchMockStock` in `server.mjs`.

```js
// server.mjs
const response = await fetchWithTimeout("https://api.github.com/repos/vercel/next.js", 2000);
```

Replace with any other public repo API endpoint, e.g. `https://api.github.com/repos/owner/repo`.

## Notes

- This project is for demonstration. It does not scrape or use Gamersberg APIs.
- The UI is a simplified clone and can be styled further to match the reference closely.
