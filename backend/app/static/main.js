const message = document.querySelector("#message");
const entryDate = document.querySelector("#entryDate");
const submit = document.querySelector("#submit");
const refresh = document.querySelector("#refresh");
const parsed = document.querySelector("#parsed");
const records = document.querySelector("#records");
const statusNode = document.querySelector("#status");

entryDate.valueAsDate = new Date();

submit.addEventListener("click", async () => {
  const text = message.value.trim();
  if (!text) {
    setStatus("Empty");
    return;
  }

  setStatus("Saving");
  const response = await fetch("/api/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      entry_date: entryDate.value || null,
      source: "web",
    }),
  });

  if (!response.ok) {
    setStatus("Error");
    parsed.textContent = await response.text();
    return;
  }

  const payload = await response.json();
  renderParsed(payload);
  message.value = "";
  await loadLogs();
  setStatus("Saved");
});

refresh.addEventListener("click", loadLogs);

loadLogs();
loadExtractionStatus();

function setStatus(label) {
  statusNode.textContent = label;
}

function renderParsed(payload) {
  const sections = [];
  const data = payload.parsed;

  sections.push(recordBlock("Extraction", {
    method: payload.extraction_method,
    error: payload.extraction_error,
  }));
  sections.push(recordBlock("Raw message", { id: payload.raw_message_id, date: data.entry_date }));

  for (const item of data.nutrition) {
    sections.push(recordBlock("Nutrition", item));
  }
  if (data.workout) {
    sections.push(recordBlock("Workout", data.workout));
  }
  if (data.wellbeing) {
    sections.push(recordBlock("Wellbeing", data.wellbeing));
  }
  for (const item of data.career) {
    sections.push(recordBlock("Career", item));
  }
  if (data.journal_text) {
    sections.push(recordBlock("Journal", { text: data.journal_text }));
  }

  if (data.missing_info_questions.length) {
    sections.push(`
      <div class="questions">
        <p>Clarify later</p>
        <ul>${data.missing_info_questions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
      </div>
    `);
  }

  parsed.innerHTML = sections.join("");
}

async function loadLogs() {
  setStatus("Loading");
  const response = await fetch("/api/logs?limit=12");
  const payload = await response.json();
  renderRecords(payload.logs);
  await loadExtractionStatus();
}

async function loadExtractionStatus() {
  const response = await fetch("/api/extraction/status");
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  const label = payload.model ? `${payload.mode}: ${payload.model}` : payload.mode;
  statusNode.title = payload.configured ? "Extractor configured" : "Extractor missing configuration";
  statusNode.textContent = label;
}

function renderRecords(logs) {
  const flat = [];
  for (const [kind, items] of Object.entries(logs)) {
    for (const item of items) {
      flat.push({ kind, item });
    }
  }

  flat.sort((a, b) => String(b.item.created_at || "").localeCompare(String(a.item.created_at || "")));

  if (!flat.length) {
    records.innerHTML = '<div class="empty">No records yet.</div>';
    return;
  }

  records.innerHTML = flat.slice(0, 24).map(({ kind, item }) => {
    const title = kind.replace("_", " ");
    return `
      <div class="record">
        <div class="record-title">
          <span>${escapeHtml(title)}</span>
          <span class="record-meta">${escapeHtml(item.entry_date || "")}</span>
        </div>
        ${fields(item)}
      </div>
    `;
  }).join("");
}

function recordBlock(title, item) {
  return `
    <div class="record">
      <div class="record-title"><span>${escapeHtml(title)}</span></div>
      ${fields(item)}
    </div>
  `;
}

function fields(item) {
  const hidden = new Set(["created_at", "raw_message_id", "source"]);
  const entries = Object.entries(item)
    .filter(([key, value]) => !hidden.has(key) && value !== null && value !== undefined && value !== "")
    .slice(0, 8);

  if (!entries.length) {
    return "";
  }

  return `
    <dl class="fields">
      ${entries.map(([key, value]) => `
        <div>
          <dt>${escapeHtml(key.replaceAll("_", " "))}</dt>
          <dd>${escapeHtml(String(value))}</dd>
        </div>
      `).join("")}
    </dl>
  `;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
