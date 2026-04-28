const message = document.querySelector("#message");
const entryDate = document.querySelector("#entryDate");
const submit = document.querySelector("#submit");
const clear = document.querySelector("#clear");
const refresh = document.querySelector("#refresh");
const parsed = document.querySelector("#parsed");
const records = document.querySelector("#records");
const statusNode = document.querySelector("#status");
const tone = document.querySelector("#tone");
const assumption = document.querySelector("#assumption");
const modeButtons = Array.from(document.querySelectorAll("[data-mode]"));

const MODE_ASSUMPTIONS = {
  auto: "Auto mode will route the message from its wording.",
  log: "Log mode stores the text even if it looks like a command.",
  briefing: "Brief mode treats the text as a summary request.",
  plot: "Plot mode expects a chart request and leaves logs unchanged.",
  memory: "Memory mode looks for durable preferences and strategies.",
};
const MODE_STATUS = {
  auto: "Routing",
  log: "Logging",
  briefing: "Briefing",
  plot: "Plotting",
  memory: "Remembering",
};
const DONE_STATUS = {
  logged: "Logged",
  memory_updated: "Remembered",
  briefing_sent: "Briefed",
  plot_sent: "Plotted",
  ignored_non_logging_reply: "Unchanged",
  completed_actions: "Completed",
};
const TONE_VALUES = Array.from(tone.options).map((option) => option.value);

entryDate.valueAsDate = new Date();
let activeMode = storedChoice("life-os-mode", "auto", Object.keys(MODE_ASSUMPTIONS));
tone.value = storedChoice("life-os-tone", "balanced", TONE_VALUES);
setMode(activeMode);

// Auto-resize textarea
message.addEventListener("input", () => {
  message.style.height = "auto";
  message.style.height = message.scrollHeight + "px";
});

submit.addEventListener("click", async () => {
  const text = message.value.trim();
  if (!text) {
    setStatus("Need text");
    return;
  }

  setLoading(true);
  setStatus(statusForMode(activeMode));
  parsed.innerHTML = '<div class="empty">Processing...</div>';

  try {
    const response = await fetch("/api/agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        entry_date: entryDate.value || null,
        source: "web",
        mode: activeMode,
        tone: tone.value,
      }),
    });

    if (!response.ok) {
      setStatus("Error");
      parsed.textContent = await response.text();
      return;
    }

    const payload = await response.json();
    renderAgentReply(payload);
    message.value = "";
    message.style.height = "auto";
    await loadLogs();
    setStatus(doneStatus(payload.status));
  } catch (err) {
    setStatus("Error");
    parsed.textContent = err.message;
  } finally {
    setLoading(false);
  }
});

clear.addEventListener("click", () => {
  message.value = "";
  message.style.height = "auto";
  parsed.innerHTML = '<div class="empty">Stopped. The draft was cleared.</div>';
  setStatus("Stopped");
});

refresh.addEventListener("click", loadLogs);
tone.addEventListener("change", () => {
  localStorage.setItem("life-os-tone", tone.value);
});

for (const button of modeButtons) {
  button.addEventListener("click", () => setMode(button.dataset.mode));
}

records.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-delete-kind]");
  if (!button) {
    return;
  }
  const kind = button.dataset.deleteKind;
  const id = button.dataset.deleteId;
  const label = button.dataset.deleteLabel || `${kind} #${id}`;
  if (!window.confirm(`Delete ${label}?`)) {
    return;
  }

  setStatus("Deleting");
  const response = await fetch(`/api/logs/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    setStatus("Delete error");
    parsed.textContent = await response.text();
    return;
  }
  const payload = await response.json();
  parsed.innerHTML = recordBlock("Deleted", {
    kind: payload.kind,
    id: payload.id,
    summary: payload.summary,
  });
  await loadLogs();
  setStatus("Deleted");
});

loadLogs();
loadExtractionStatus();

function setStatus(label) {
  statusNode.textContent = label;
  statusNode.style.borderColor = "var(--ink)";
  setTimeout(() => {
    statusNode.style.borderColor = "var(--line)";
  }, 1000);
}

function setLoading(isLoading) {
  submit.disabled = isLoading;
  submit.textContent = isLoading ? "Sending..." : "Send";
  submit.style.opacity = isLoading ? "0.7" : "1";
}

function setMode(mode) {
  activeMode = mode;
  localStorage.setItem("life-os-mode", activeMode);
  for (const button of modeButtons) {
    button.classList.toggle("active", button.dataset.mode === activeMode);
  }
  assumption.textContent = MODE_ASSUMPTIONS[activeMode] || MODE_ASSUMPTIONS.auto;
}

function statusForMode(mode) {
  return MODE_STATUS[mode] || "Working";
}

function doneStatus(status) {
  return DONE_STATUS[status] || "Done";
}

function renderAgentReply(payload) {
  const sections = [];
  if (payload.confirmation) {
    sections.push(messageBlock("Reply", payload.confirmation));
  }
  if (payload.assumption) {
    sections.push(messageBlock("Assumption", payload.assumption));
  }
  if (payload.parsed) {
    sections.push(...parsedSections(payload));
  } else if (!sections.length) {
    sections.push('<div class="empty">No structured data returned.</div>');
  }
  parsed.innerHTML = sections.join("");
}

function parsedSections(payload) {
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

  return sections;
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
          <span class="record-meta">${escapeHtml(item.entry_date || item.date || "")}</span>
        </div>
        ${fields(item)}
        <div class="record-actions">
          <button
            type="button"
            class="ghost danger"
            data-delete-kind="${escapeHtml(kind)}"
            data-delete-id="${escapeHtml(String(item.id))}"
            data-delete-label="${escapeHtml(`${title} #${item.id}`)}"
          >Delete</button>
        </div>
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

function messageBlock(title, text) {
  return `
    <div class="record reply">
      <div class="record-title"><span>${escapeHtml(title)}</span></div>
      <p>${escapeHtml(text).replaceAll("\n", "<br>")}</p>
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

function storedChoice(key, fallback, allowed) {
  const value = localStorage.getItem(key);
  return allowed.includes(value) ? value : fallback;
}
