const express = require("express");
const os = require("os");
const path = require("path");

const app = express();
const port = process.env.PORT || 8080;

// Health check (for ALB and verifier)
app.get("/health", (_req, res) => {
  res.status(200).send("OK");
});

// API for the sample webpage (hostname, version, timestamp)
app.get("/api/info", (_req, res) => {
  res.json({
    hostname: os.hostname(),
    version: process.env.APP_VERSION || "dev",
    timestamp: new Date().toISOString(),
  });
});

// Sample webpage (static)
app.use(express.static(path.join(__dirname, "public")));
app.get("/", (_req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

app.listen(port, () => {
  console.log(`Server listening on ${port}`);
});
