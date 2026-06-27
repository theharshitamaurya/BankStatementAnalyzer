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
  "Initializing neural extraction framework...",
  "Scanning PDF layer metadata...",
  "Isolating tabular structures...",
  "Applying ML categorization models...",
  "Reconciling ledger hashes...",
  "Assembling final Excel matrices...",
  "Finalizing artifact generation..."
];

let tickerInterval;
let messageIdx = 0;

function startLoader() {
  loaderOverlay.classList.remove("hidden");
  setTimeout(() => loaderOverlay.classList.add("visible"), 10);
  
  messageIdx = 0;
  tickerText.textContent = messages[messageIdx];
  
  auditMetricStatus.textContent = "Booting";
  auditMetricRecon.textContent = "Standby";
  auditMetricSheets.textContent = "0/15";
  
  let ticks = 0;
  tickerInterval = setInterval(() => {
    ticks++;
    if (ticks % 3 === 0) {
      messageIdx = (messageIdx + 1) % messages.length;
      tickerText.textContent = messages[messageIdx];
    }
    
    if (ticks === 2) auditMetricStatus.textContent = "Extracting";
    if (ticks === 5) auditMetricStatus.textContent = "Analyzing";
    if (ticks === 8) auditMetricStatus.textContent = "Compiling";
    if (ticks > 12) auditMetricStatus.textContent = "Finalizing";
    
    if (ticks === 4) auditMetricRecon.textContent = "Active";
    if (ticks === 10) auditMetricRecon.textContent = "Verified";
    
    // Instead of a fake counter, show an active state
    auditMetricSheets.textContent = "Calculating...";
  }, 600);
}

function stopLoader() {
  clearInterval(tickerInterval);
  loaderOverlay.classList.remove("visible");
  setTimeout(() => loaderOverlay.classList.add("hidden"), 500);
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
  statusBox.className = `status-banner ${type}`;
}

function updateFiles(files) {
  const pdfs = [...files].filter((file) => file.name.toLowerCase().endsWith(".pdf"));
  generateBtn.disabled = pdfs.length === 0;
  fileCount.textContent = pdfs.length ? `${pdfs.length} Document${pdfs.length === 1 ? "" : "s"} Ready` : "No files selected";
  fileNames.textContent = pdfs.map((file) => file.name).join(", ");
  result.hidden = true;
  setStatus(pdfs.length ? "Engine ready for initialization." : "System ready. Awaiting input.", "idle");
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
  setStatus("Commencing neural extraction sequence...", "working");
  
  loaderOverlay.classList.remove("hidden");
  setTimeout(() => loaderOverlay.classList.add("visible"), 10);
  
  auditMetricStatus.textContent = "Booting engine...";
  auditMetricRecon.textContent = "Standby";
  auditMetricSheets.textContent = "Waiting...";
  tickerText.textContent = "Uploading securely...";

  try {
    const response = await fetch("/api/generate", { method: "POST", body });
    if (!response.ok && !response.body) {
       throw new Error("Server error " + response.status);
    }
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); 
      
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const data = JSON.parse(line);
          
          if (data.type === 'progress') {
            if (data.message) {
              tickerText.textContent = data.message;
              auditMetricStatus.textContent = "Processing";
            }
            if (data.sheet) {
              auditMetricStatus.textContent = `Building Sheet`;
              auditMetricRecon.textContent = data.sheet;
              auditMetricSheets.textContent = `${data.current} / ${data.total}`;
            }
          } 
          else if (data.type === 'error') {
            const detail = Array.isArray(data.details)
              ? data.details.map((item) => `${item.file}: ${item.issue}`).join("; ")
              : data.details || data.error;
            throw new Error(detail || "Processing sequence failed.");
          }
          else if (data.type === 'done') {
            const payload = data.payload;
            statementsMetric.textContent = payload.statements;
            transactionsMetric.textContent = payload.transactions;
            receiptsMetric.textContent = formatMoney(payload.total_receipts);
            paymentsMetric.textContent = formatMoney(payload.total_payments);
            downloadLink.href = payload.downloadUrl;
            
            result.hidden = false;
            setStatus("Analysis completed successfully. Artifact ready.", "success");
          }
        } catch (e) {
          if (e.message !== "Unexpected end of JSON input") {
             if (e.message !== "Processing sequence failed." && !e.message.includes("failed") && !e.message.includes("Error")) {
                console.error("Parse error:", e);
             } else {
                throw e;
             }
          }
        }
      }
    }
    
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    loaderOverlay.classList.remove("visible");
    setTimeout(() => loaderOverlay.classList.add("hidden"), 500);
    generateBtn.disabled = input.files.length === 0;
  }
});
