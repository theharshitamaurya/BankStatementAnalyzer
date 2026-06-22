import cgi
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse


ROOT = pathlib.Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
PUBLIC_DIR = ROOT / "public"
JOBS_DIR = WORKSPACE / "work" / "upload_jobs"
OUTPUTS_DIR = WORKSPACE / "outputs"
PYTHON_EXE = pathlib.Path(os.environ.get("HDFC_PYTHON_EXE", sys.executable))
NODE_EXE = pathlib.Path(
    os.environ.get(
        "HDFC_NODE_EXE",
        r"C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe",
    )
)




class HdfcHandler(BaseHTTPRequestHandler):
    server_version = "BankStatementTool/1.0"

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type, download_name=None):
        data = pathlib.Path(path).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            return self.send_file(PUBLIC_DIR / "index.html", "text/html; charset=utf-8")
        if parsed.path == "/styles.css":
            return self.send_file(PUBLIC_DIR / "styles.css", "text/css; charset=utf-8")
        if parsed.path == "/app.js":
            return self.send_file(PUBLIC_DIR / "app.js", "application/javascript; charset=utf-8")
        if parsed.path.startswith("/download/"):
            return self.handle_download(parsed.path)
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/generate":
            return self.handle_generate()
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def handle_download(self, request_path):
        job_id = unquote(request_path.split("/", 2)[2])
        if not job_id or any(ch not in "abcdef0123456789-" for ch in job_id.lower()):
            return self.send_error(HTTPStatus.BAD_REQUEST, "Invalid job id")
        output_path = OUTPUTS_DIR / f"bank_statement_analysis_{job_id}.xlsx"
        if not output_path.exists():
            output_path = JOBS_DIR / job_id / "bank_statement_analysis.xlsx"
        if not output_path.exists():
            return self.send_error(HTTPStatus.NOT_FOUND, "Workbook not found")
            
        summary_path = JOBS_DIR / job_id / "summary.json"
        download_name = "bank_statement_analysis.xlsx"
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                if summary.get("dynamic_filename"):
                    download_name = summary["dynamic_filename"]
            except Exception:
                pass
                
        self.send_file(
            output_path,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            download_name,
        )

    def handle_generate(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Upload PDFs using multipart/form-data."})

        job_id = str(uuid.uuid4())
        job_dir = JOBS_DIR / job_id
        upload_dir = job_dir / "uploads"
        data_dir = job_dir / "data"
        upload_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": content_type,
                    "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                },
            )
            files = form["pdfs"] if "pdfs" in form else []
            if not isinstance(files, list):
                files = [files]

            saved = []
            for item in files:
                if not getattr(item, "filename", ""):
                    continue
                safe_name = pathlib.Path(item.filename).name
                if not safe_name.lower().endswith(".pdf"):
                    continue
                target = upload_dir / safe_name
                with target.open("wb") as fp:
                    shutil.copyfileobj(item.file, fp)
                saved.append(safe_name)

            if not saved:
                return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Please upload at least one PDF file."})

            summary_path = job_dir / "summary.json"
            extract = subprocess.run(
                [
                    str(PYTHON_EXE),
                    str(ROOT / "extract_bank.py"),
                    "--input-dir",
                    str(upload_dir),
                    "--work-dir",
                    str(data_dir),
                    "--summary-json",
                    str(summary_path),
                ],
                cwd=str(WORKSPACE),
                capture_output=True,
                text=True,
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
            if extract.returncode != 0 or not summary.get("transactions"):
                summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
                return self.send_json(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    {
                        "error": "The PDFs were uploaded, but one or more statements could not be reconciled.",
                        "details": summary.get("issues") or extract.stderr[-2000:],
                    },
                )

            output_path = job_dir / "bank_statement_analysis.xlsx"
            env = os.environ.copy()
            env.update(
                {
                    "HDFC_WORK_DIR": str(data_dir),
                    "HDFC_OUTPUT_DIR": str(job_dir),
                    "HDFC_OUTPUT_XLSX": str(output_path),
                    "HDFC_SKIP_PREVIEWS": "1",
                }
            )
            build = subprocess.run(
                [str(NODE_EXE), str(ROOT / "build_hdfc_workbook.mjs")],
                cwd=str(WORKSPACE),
                env=env,
                capture_output=True,
                text=True,
            )
            if build.returncode != 0 or not output_path.exists():
                return self.send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "Excel generation failed.", "details": (build.stderr or build.stdout)[-2000:]},
                )

            # Add chart via openpyxl
            chart_script = ROOT / "add_chart.py"
            if chart_script.exists():
                subprocess.run(
                    [str(PYTHON_EXE), str(chart_script), str(output_path)],
                    cwd=str(WORKSPACE),
                    capture_output=True,
                    text=True,
                )
                

            summary.update(
                {
                    "jobId": job_id,
                    "uploadedFiles": saved,
                    "downloadUrl": f"/download/{job_id}",
                    "generatedAt": int(time.time()),
                }
            )
            return self.send_json(HTTPStatus.OK, summary)
        except Exception as exc:
            return self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


def main():
    port = int(os.environ.get("PORT", "8765"))
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), HdfcHandler)
    print(f"Bank PDF to Excel app running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
