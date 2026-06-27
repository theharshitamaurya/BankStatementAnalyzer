import express from 'express';
import multer from 'multer';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs/promises';
import { existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { v4 as uuidv4 } from 'uuid';
import { buildWorkbook } from './build_hdfc_workbook.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = __dirname;
const WORKSPACE = path.resolve(ROOT, '..');
const PUBLIC_DIR = path.join(ROOT, 'public');
const JOBS_DIR = path.join(WORKSPACE, 'work', 'upload_jobs');
const OUTPUTS_DIR = path.join(WORKSPACE, 'outputs');

const PYTHON_EXE = process.env.HDFC_PYTHON_EXE || 'python';
const NODE_EXE = process.env.HDFC_NODE_EXE || 'node';

const app = express();
const port = parseInt(process.env.PORT || '8765', 10);

mkdirSync(JOBS_DIR, { recursive: true });
mkdirSync(OUTPUTS_DIR, { recursive: true });

const upload = multer({ dest: path.join(WORKSPACE, 'work', 'tmp') });

app.use(express.static(PUBLIC_DIR));

const runCommand = (command, args, options) => {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, options);
    let stdout = '';
    let stderr = '';
    child.stdout.on('data', (data) => { stdout += data.toString(); });
    child.stderr.on('data', (data) => { stderr += data.toString(); });
    child.on('error', reject);
    child.on('close', (code) => {
      resolve({ code, stdout, stderr });
    });
  });
};

app.get('/download/:jobId', async (req, res) => {
  const { jobId } = req.params;
  if (!/^[a-f0-9-]+$/i.test(jobId)) {
    return res.status(400).send('Invalid job id');
  }

  let outputPath = path.join(OUTPUTS_DIR, `bank_statement_analysis_${jobId}.xlsx`);
  if (!existsSync(outputPath)) {
    outputPath = path.join(JOBS_DIR, jobId, 'bank_statement_analysis.xlsx');
  }

  if (!existsSync(outputPath)) {
    return res.status(404).send('Workbook not found');
  }

  const summaryPath = path.join(JOBS_DIR, jobId, 'summary.json');
  let downloadName = 'bank_statement_analysis.xlsx';
  if (existsSync(summaryPath)) {
    try {
      const summaryContent = await fs.readFile(summaryPath, 'utf-8');
      const summary = JSON.parse(summaryContent);
      if (summary.dynamic_filename) {
        downloadName = summary.dynamic_filename;
      }
    } catch (err) {}
  }

  res.download(outputPath, downloadName);
});

app.post('/api/generate', upload.array('pdfs'), async (req, res) => {
  try {
    if (!req.files || req.files.length === 0) {
      return res.status(400).json({ error: 'Please upload at least one PDF file.' });
    }

    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.setHeader('Transfer-Encoding', 'chunked');

    const sendEvent = (data) => {
      res.write(JSON.stringify(data) + '\n');
    };

    const jobId = uuidv4();
    const jobDir = path.join(JOBS_DIR, jobId);
    const uploadDir = path.join(jobDir, 'uploads');
    const dataDir = path.join(jobDir, 'data');
    
    mkdirSync(uploadDir, { recursive: true });
    mkdirSync(dataDir, { recursive: true });

    const statementPassword = req.body.statementPassword || '';
    const saved = [];

    for (const file of req.files) {
      const safeName = file.originalname;
      if (!safeName.toLowerCase().endsWith('.pdf')) continue;
      const target = path.join(uploadDir, safeName);
      await fs.rename(file.path, target);
      saved.push(safeName);
    }

    if (saved.length === 0) {
      sendEvent({ type: 'error', error: 'Please upload at least one valid PDF file.' });
      return res.end();
    }

    sendEvent({ type: 'progress', message: 'Extracting data from PDFs...' });

    const summaryPath = path.join(jobDir, 'summary.json');
    const extractArgs = [
      path.join(ROOT, 'extract_bank.py'),
      '--input-dir', uploadDir,
      '--work-dir', dataDir,
      '--summary-json', summaryPath
    ];
    if (statementPassword) {
      extractArgs.push('--password', statementPassword);
    }

    const extract = await runCommand(PYTHON_EXE, extractArgs, { cwd: WORKSPACE });
    
    let summary = {};
    if (existsSync(summaryPath)) {
      try {
        summary = JSON.parse(await fs.readFile(summaryPath, 'utf-8'));
      } catch (e) {}
    }

    if (extract.code !== 0 || !summary.transactions) {
      sendEvent({
        type: 'error',
        error: 'The PDFs were uploaded, but one or more statements could not be reconciled.',
        details: summary.issues || extract.stderr.slice(-2000)
      });
      return res.end();
    }

    sendEvent({ type: 'progress', message: 'Initializing workbook generation...' });

    const outputPath = path.join(jobDir, 'bank_statement_analysis.xlsx');
    process.env.HDFC_SKIP_PREVIEWS = '1';

    try {
      await buildWorkbook({
        workDir: dataDir,
        outputDir: jobDir,
        outputPath: outputPath
      }, (sheet, current, total) => {
        sendEvent({ type: 'progress', sheet, current, total });
      });
    } catch (e) {
      sendEvent({
        type: 'error',
        error: 'Excel generation failed.',
        details: e.message
      });
      return res.end();
    }

    if (!existsSync(outputPath)) {
      sendEvent({
        type: 'error',
        error: 'Excel generation failed.',
        details: 'Output file was not created.'
      });
      return res.end();
    }

    sendEvent({ type: 'progress', message: 'Finalizing formatting and chart generation...' });

    const chartScript = path.join(ROOT, 'add_chart.py');
    if (existsSync(chartScript)) {
      await runCommand(PYTHON_EXE, [chartScript, outputPath], { cwd: WORKSPACE });
    }

    summary.jobId = jobId;
    summary.uploadedFiles = saved;
    summary.downloadUrl = `/download/${jobId}`;
    summary.generatedAt = Math.floor(Date.now() / 1000);

    sendEvent({ type: 'done', payload: summary });
    res.end();

  } catch (err) {
    console.error(err);
    if (!res.headersSent) {
      res.status(500).json({ error: err.message });
    } else {
      res.write(JSON.stringify({ type: 'error', error: err.message }) + '\n');
      res.end();
    }
  }
});

app.listen(port, '0.0.0.0', () => {
  console.log(`Bank PDF to Excel app running at http://127.0.0.1:${port}`);
});
