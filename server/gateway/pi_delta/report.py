"""Aggregate measured four-mode benchmark CSV without inventing missing numbers."""
import argparse
import csv
import json
import statistics
from pathlib import Path


def summarize(rows):
    result = {}
    for mode in ("full", "gzip", "delta", "delta-gzip"):
        subset = [r for r in rows if r["mode"] == mode]
        if not subset:
            continue
        def nums(key):
            return [float(r[key]) for r in subset if r.get(key) not in ("", None)]
        total_http = sum(int(r["http_request_body_bytes"]) for r in subset)
        total_forward = sum(int(r["full_request_bytes"]) for r in subset)
        def describe(key):
            points = nums(key)
            if not points:
                return {"n": 0, "median": None, "p95": None}
            points.sort()
            idx = max(0, min(len(points) - 1, int(0.95 * (len(points) - 1) + 0.999999)))
            return {"n": len(points), "median": round(statistics.median(points), 3), "p95": round(points[idx], 3)}
        result[mode] = {
            "n": len(subset),
            "http_upload_bytes": total_http,
            "logical_upstream_bytes": total_forward,
            "ttft_ms": describe("ttft_ms"),
            "first_byte_ms": describe("first_byte_ms"),
            "total_ms": describe("total_ms"),
            "prompt_tokens": describe("prompt_tokens"),
        }
    baseline = result.get("full", {}).get("http_upload_bytes")
    for mode, summary in result.items():
        summary["upload_savings_vs_full_pct"] = round(100 * (1 - summary["http_upload_bytes"] / baseline), 3) if baseline else None
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv_path", nargs="?", default="benchmarks/results/benchmark.csv")
    p.add_argument("--output", default="benchmarks/results/report.md")
    args = p.parse_args()
    with open(args.csv_path, newline="", encoding="utf-8") as f:
        data = list(csv.DictReader(f))
    if not data:
        raise SystemExit("empty benchmark data")
    summary = summarize(data)
    dst = Path(args.output)
    dst.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Pi ↔ vLLM transport experimental A/B report",
        "",
        "Measured source CSV: " + args.csv_path,
        "",
        "| Mode | Turns | HTTP upload bytes | Savings vs Full | TTFT median (ms) | TTFT P95 (ms) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for mode, s in summary.items():
        savings = "N/A" if s["upload_savings_vs_full_pct"] is None else str(s["upload_savings_vs_full_pct"]) + "%"
        ttft = s["ttft_ms"]
        lines.append(f'| {mode} | {s["n"]} | {s["http_upload_bytes"]} | {savings} | {ttft["median"]} | {ttft["p95"]} |')
    lines += [
        "",
        "## Interpretation",
        "- Savings measure HTTP POST body bytes only, NOT SSH/TCP wire bytes.",
        "- TTFT is first streamed text/tool-call delta; N/A means no observed content delta.",
        "- P0 native Pi→vLLM is a separate latency baseline; this report only compares Gateway transport modes.",
        "- GPU prefix cache / hardware details must be collected separately and joined using experiment manifest.",
    ]
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    dst.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(dst)
    print(dst.with_suffix(".json"))


if __name__ == "__main__":
    main()
