import express from "express";
import cors from "cors";
import fetch from "node-fetch";

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static("public"));

async function fetchWithTimeout(url, ms = 2000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), ms);
  try {
    const resp = await fetch(url, { signal: controller.signal, headers: { "User-Agent": "gag-stock-clone" } });
    clearTimeout(id);
    return resp;
  } catch (e) {
    clearTimeout(id);
    throw e;
  }
}

function simulateStock() {
  const now = new Date().toISOString();
  return [
    { category: "Seeds", item: "Sunflower Seed", inStock: Math.random() > 0.5, lastSeen: now },
    { category: "Eggs", item: "Chicken Egg", inStock: Math.random() > 0.5, lastSeen: now },
    { category: "Gear", item: "Watering Can", inStock: Math.random() > 0.5, lastSeen: now },
  ];
}

async function fetchMockStock() {
  try {
    const response = await fetchWithTimeout("https://api.github.com/repos/vercel/next.js", 2000);
    const repo = await response.json();
    const now = new Date().toISOString();
    return [
      { category: "Seeds", item: "Sunflower Seed", inStock: (repo.stargazers_count ?? 0) % 2 === 0, lastSeen: now },
      { category: "Eggs", item: "Chicken Egg", inStock: (repo.open_issues_count ?? 0) % 2 === 1, lastSeen: now },
      { category: "Gear", item: "Watering Can", inStock: true, lastSeen: now }
    ];
  } catch (e) {
    return simulateStock();
  }
}

app.get("/api/stock", async (_req, res) => {
  const items = await fetchMockStock();
  res.json({ updatedAt: new Date().toISOString(), items });
});

app.get("/api/stock/stream", async (req, res) => {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive"
  });

  let active = true;
  req.on("close", () => { active = false; });

  async function tick() {
    while (active) {
      const items = await fetchMockStock();
      const payload = { updatedAt: new Date().toISOString(), items };
      res.write(`event: stock\n`);
      res.write(`data: ${JSON.stringify(payload)}\n\n`);
      await new Promise(r => setTimeout(r, 10000));
    }
  }

  tick();
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`server http://localhost:${PORT}`));
