const form = document.querySelector("#uploadForm");
const input = document.querySelector("#pdfInput");
const statementPassword = document.querySelector("#statementPassword");
const dropZone = document.querySelector("#dropZone");
const fileCount = document.querySelector("#fileCount");
const fileNames = document.querySelector("#fileNames");
const generateBtn = document.querySelector("#generateBtn");
const statusBox = document.querySelector("#status");
const result = document.querySelector("#result");
const downloadLink = document.querySelector("#downloadLink");

const statementsMetric = document.querySelector("#statementsMetric");
const transactionsMetric = document.querySelector("#transactionsMetric");
const receiptsMetric = document.querySelector("#receiptsMetric");
const paymentsMetric = document.querySelector("#paymentsMetric");

const loaderOverlay = document.getElementById("loaderOverlay");
const tickerText = document.getElementById("tickerText");
const auditMetricStatus = document.getElementById("auditMetricStatus");
const auditMetricRecon = document.getElementById("auditMetricRecon");
const auditMetricSheets = document.getElementById("auditMetricSheets");

const messages = [
  "Initializing secure parsing framework...",
  "Extracting transactional metadata...",
  "Cross-referencing bank identifier formats...",
  "Applying ML-based categorization heuristics...",
  "Computing monthly velocity metrics...",
  "Generating audit-ready Excel sheets...",
  "Finalizing formatting and hyperlinking...",
];

let tickerInterval;
let messageIdx = 0;

function startLoader() {
  loaderOverlay.classList.remove("hidden");
  setTimeout(() => loaderOverlay.classList.add("visible"), 10);
  
  messageIdx = 0;
  tickerText.textContent = messages[messageIdx];
  tickerText.classList.remove("fade");
  
  auditMetricStatus.textContent = "Verifying Files";
  auditMetricRecon.textContent = "Pending";
  auditMetricSheets.textContent = "0 / 15";
  
  let ticks = 0;

  tickerInterval = setInterval(() => {
    ticks++;
    
    if (ticks % 3 === 0) {
      tickerText.classList.add("fade");
      setTimeout(() => {
        messageIdx = (messageIdx + 1) % messages.length;
        tickerText.textContent = messages[messageIdx];
        tickerText.classList.remove("fade");
      }, 250);
    }
    
    if (ticks === 2) auditMetricStatus.textContent = "Parsing Text";
    if (ticks === 5) auditMetricStatus.textContent = "Categorizing";
    if (ticks === 8) auditMetricStatus.textContent = "Building Excel";
    if (ticks > 12) auditMetricStatus.textContent = "Optimizing UI";
    
    if (ticks === 4) auditMetricRecon.textContent = "In Progress";
    if (ticks === 10) auditMetricRecon.textContent = "Complete";
    
    if (ticks > 5 && ticks < 15) {
      auditMetricSheets.textContent = `${Math.min(15, (ticks - 5) * 2)} / 15`;
    }
  }, 500);
}

function stopLoader() {
  clearInterval(tickerInterval);
  loaderOverlay.classList.remove("visible");
  setTimeout(() => loaderOverlay.classList.add("hidden"), 400);
}

function formatMoney(value) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 2,
  }).format(Number(value || 0));
}

function setStatus(message, type = "idle") {
  statusBox.textContent = message;
  statusBox.className = `status ${type}`;
}

function updateFiles(files) {
  const pdfs = [...files].filter((file) => file.name.toLowerCase().endsWith(".pdf"));
  generateBtn.disabled = pdfs.length === 0;
  fileCount.textContent = pdfs.length ? `${pdfs.length} PDF${pdfs.length === 1 ? "" : "s"} selected` : "No PDFs selected";
  fileNames.textContent = pdfs.map((file) => file.name).join(", ");
  result.hidden = true;
  setStatus(pdfs.length ? "Ready to generate." : "Waiting for PDFs.", "idle");
}

input.addEventListener("change", () => updateFiles(input.files));

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("dragover");
});

dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragover");
  input.files = event.dataTransfer.files;
  updateFiles(input.files);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!input.files.length) return;

  const body = new FormData();
  [...input.files].forEach((file) => {
    if (file.name.toLowerCase().endsWith(".pdf")) {
      body.append("pdfs", file);
    }
  });
  const password = statementPassword.value.trim();
  if (password) {
    body.append("statementPassword", password);
  }

  generateBtn.disabled = true;
  result.hidden = true;
  setStatus("Reading PDFs and building Excel. This can take a little while.", "working");
  startLoader();

  try {
    const response = await fetch("/api/generate", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(payload.details)
        ? payload.details.map((item) => `${item.file}: ${item.issue}`).join("; ")
        : payload.details || payload.error;
      throw new Error(detail || "Generation failed.");
    }

    statementsMetric.textContent = payload.statements;
    transactionsMetric.textContent = payload.transactions;
    receiptsMetric.textContent = formatMoney(payload.total_receipts);
    paymentsMetric.textContent = formatMoney(payload.total_payments);
    downloadLink.href = payload.downloadUrl;
    result.hidden = false;
    setStatus("Excel workbook is ready.", "success");
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    stopLoader();
    generateBtn.disabled = input.files.length === 0;
  }
});
