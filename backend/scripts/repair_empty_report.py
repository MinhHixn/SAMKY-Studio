"""Regenerate a verified empty local report, keeping a backup and the same URL."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_id")
    parser.add_argument("--backend-pid", type=int, required=True)
    args = parser.parse_args()
    import psutil

    backend = Path(__file__).resolve().parents[1]
    process = psutil.Process(args.backend_pid)
    if Path(process.cwd()).resolve() != backend.parent or "backend\\run.py" not in " ".join(process.cmdline()).replace("/", "\\"):
        raise RuntimeError("PID is not this project's backend")
    # Keep the running server's model and connection settings in memory only.
    os.environ.update(process.environ())
    sys.path.insert(0, str(backend))
    from app.services.report_agent import ReportAgent, ReportManager, ReportStatus
    from app.services.graph_tools import GraphToolsService
    from app.storage import Neo4jStorage

    report = ReportManager.get_report(args.report_id)
    if (not report or report.status not in (ReportStatus.COMPLETED, ReportStatus.FAILED)
            or (report.outline and any(s.content.strip() for s in report.outline.sections))
            or ReportManager.get_generated_sections(args.report_id)):
        raise RuntimeError("Repair is restricted to finished/failed reports with no section content")
    source = Path(ReportManager._get_report_folder(args.report_id)).resolve()
    if source.parent != Path(ReportManager.REPORTS_DIR).resolve():
        raise RuntimeError("Report path is outside the report directory")
    backup = backend / "test_run" / (args.report_id + "_before_repair_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copytree(source, backup)
    print("Backup:", backup, flush=True)
    storage = Neo4jStorage()
    try:
        agent = ReportAgent(
            graph_id=report.graph_id,
            simulation_id=report.simulation_id,
            simulation_requirement=report.simulation_requirement,
            graph_tools=GraphToolsService(storage=storage),
        )
        recovered = agent.generate_report(
            report_id=report.report_id,
            progress_callback=lambda stage, progress, message: print(stage, progress, message, flush=True),
        )
        print(json.dumps({"report_id": recovered.report_id, "status": recovered.status.value,
                          "sections": len(recovered.outline.sections) if recovered.outline else 0,
                          "characters": len(recovered.markdown_content), "error": recovered.error}), flush=True)
        if recovered.status != ReportStatus.COMPLETED:
            raise RuntimeError(recovered.error or "Report regeneration failed")
    finally:
        storage.close()


if __name__ == "__main__":
    main()
