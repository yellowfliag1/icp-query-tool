import csv
import io
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from miit_icp_auto_query import MiitIcpAutoClient


app = FastAPI(title="MIIT ICP Query Web")


HTML_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ICP备案查询</title>
  <style>
    :root {
      --bg: #eef3f8;
      --card: #fff;
      --line: #d7e1eb;
      --head: #f2f6fb;
      --text: #1f2937;
      --sub: #6b7280;
      --primary: #1f8ae6;
      --ok: #0f766e;
      --bad: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    .wrap { max-width: 1280px; margin: 18px auto; padding: 0 12px; }
    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 12px;
      overflow: hidden;
    }
    .hd {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      font-weight: 700;
      background: linear-gradient(90deg, #f8fbff, #f3f7fc);
    }
    .bd { padding: 12px 14px; }
    .row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
    .field { min-width: 170px; display: flex; flex-direction: column; gap: 6px; }
    label { font-size: 13px; color: var(--sub); }
    input, select, textarea, button {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      background: #fff;
      font-size: 14px;
      outline: none;
    }
    textarea { width: 100%; min-height: 120px; resize: vertical; line-height: 1.5; }
    input:focus, select:focus, textarea:focus { border-color: #7cb8f4; }
    .btn {
      border-color: var(--primary);
      background: var(--primary);
      color: #fff;
      font-weight: 600;
      min-width: 120px;
      cursor: pointer;
    }
    .btn-alt {
      background: #fff;
      color: var(--text);
      min-width: 120px;
      font-weight: 600;
      cursor: pointer;
    }
    .btn:disabled, .btn-alt:disabled { opacity: .6; cursor: not-allowed; }
    .status { margin-top: 8px; font-size: 13px; color: var(--sub); }
    .ok { color: var(--ok); }
    .bad { color: var(--bad); }
    .muted { font-size: 12px; color: var(--sub); }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { border: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }
    th { background: var(--head); font-weight: 700; }
    .op-btn {
      border: 1px solid var(--primary);
      color: var(--primary);
      background: #fff;
      border-radius: 4px;
      padding: 4px 10px;
      cursor: pointer;
      font-size: 13px;
    }
    .err { color: var(--bad); white-space: pre-wrap; word-break: break-all; }
    .sec-title {
      margin-top: 8px;
      margin-bottom: 8px;
      font-size: 16px;
      font-weight: 700;
      border-bottom: 2px solid #4f9be4;
      display: inline-block;
      padding-bottom: 4px;
    }
    .kv { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
    .kv th, .kv td { border: 1px solid var(--line); padding: 8px; }
    .kv th { width: 220px; background: var(--head); font-weight: 600; color: #374151; }
    .hidden { display: none; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div class="hd">ICP备案查询（公司名/域名，批量）</div>
      <div class="bd">
        <div class="row">
          <div class="field">
            <label>服务类型</label>
            <select id="serviceType">
              <option value="1" selected>网站(1)</option>
              <option value="6">APP(6)</option>
              <option value="7">小程序(7)</option>
              <option value="8">快应用(8)</option>
            </select>
          </div>
          <div class="field">
            <label>验证码重试</label>
            <input id="retries" type="number" min="1" max="20" value="8" />
          </div>
          <div class="field">
            <label>请求通道</label>
            <select id="transport">
              <option value="curl" selected>curl(推荐)</option>
              <option value="requests">requests</option>
            </select>
          </div>
          <div class="field">
            <label>批量间隔(秒)</label>
            <input id="delaySec" type="number" min="0" max="5" step="0.1" value="0.2" />
          </div>
        </div>
        <div class="row">
          <div style="flex: 1;">
            <label>查询词（每行一个，可填主体名或域名）</label>
            <textarea id="keywords">深圳市腾讯计算机系统有限公司
sf-express.com</textarea>
            <div class="muted">结果列表只展示核心字段；点“详情”查看完整字段（空值自动隐藏）。</div>
          </div>
        </div>
        <div class="row">
          <button id="runBtn" class="btn">搜索</button>
          <button id="csvBtn" class="btn-alt" disabled>导出CSV</button>
        </div>
        <div id="status" class="status"></div>
      </div>
    </div>

    <div class="card">
      <div class="hd">搜索结果</div>
      <div class="bd">
        <table>
          <thead>
            <tr>
              <th style="width: 60px;">序号</th>
              <th style="width: 220px;">查询词</th>
              <th style="width: 140px;">主办单位名称</th>
              <th style="width: 120px;">主办单位性质</th>
              <th style="width: 180px;">服务备案号</th>
              <th style="width: 130px;">审核日期</th>
              <th style="width: 130px;">状态</th>
              <th style="width: 90px;">操作</th>
            </tr>
          </thead>
          <tbody id="resultBody"></tbody>
        </table>
      </div>
    </div>

    <div id="detailCard" class="card hidden">
      <div class="hd">详情</div>
      <div class="bd">
        <div id="detailHint" class="muted"></div>
        <div id="subjectBlock" class="hidden">
          <div class="sec-title">ICP备案主体信息</div>
          <table class="kv"><tbody id="subjectBody"></tbody></table>
        </div>
        <div id="serviceBlock" class="hidden">
          <div class="sec-title">ICP备案服务信息</div>
          <table class="kv"><tbody id="serviceBody"></tbody></table>
        </div>
        <div id="otherBlock" class="hidden">
          <div class="sec-title">其他信息</div>
          <table class="kv"><tbody id="otherBody"></tbody></table>
        </div>
      </div>
    </div>
  </div>

  <script>
    const runBtn = document.getElementById("runBtn");
    const csvBtn = document.getElementById("csvBtn");
    const statusEl = document.getElementById("status");
    const resultBody = document.getElementById("resultBody");
    const detailCard = document.getElementById("detailCard");
    const detailHint = document.getElementById("detailHint");
    const subjectBlock = document.getElementById("subjectBlock");
    const serviceBlock = document.getElementById("serviceBlock");
    const otherBlock = document.getElementById("otherBlock");
    const subjectBody = document.getElementById("subjectBody");
    const serviceBody = document.getElementById("serviceBody");
    const otherBody = document.getElementById("otherBody");

    let lastResults = [];
    let flatRows = [];

    const labelMap = {
      domain: "域名",
      domainId: "域名ID",
      unitName: "主办单位名称",
      natureName: "主办单位性质",
      leaderName: "负责人",
      mainId: "主体ID",
      mainLicence: "ICP主体备案号",
      serviceId: "服务ID",
      serviceLicence: "服务备案号",
      serviceName: "访问名称",
      contentTypeName: "服务名称",
      accessName: "访问名称",
      appName: "应用名称",
      appVersion: "应用版本",
      appStore: "应用商店",
      miniProgramName: "小程序名称",
      miniName: "小程序名称",
      fastAppName: "快应用名称",
      limitAccess: "服务前置审批项",
      updateRecordTime: "审核日期",
    };

    function esc(v) {
      return String(v ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function lines(v) {
      return v.split(/\\r?\\n/).map(s => s.trim()).filter(Boolean);
    }

    function isEmpty(v) {
      return v === null || v === undefined || v === "" ||
             (Array.isArray(v) && v.length === 0) ||
             (typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === 0);
    }

    function toDisplayKey(k) {
      return labelMap[k] || k;
    }

    function splitSections(rec) {
      const src = rec || {};
      const subject = {};
      const service = {};
      const other = {};

      // 核心字段始终展示（即便空），避免“访问名称”等关键项缺失。
      const subjectRequired = ["mainLicence", "updateRecordTime", "unitName", "natureName"];
      const serviceRequired = ["serviceLicence", "serviceName", "contentTypeName", "accessName", "appName", "miniProgramName", "fastAppName", "limitAccess"];

      for (const k of subjectRequired) {
        subject[k] = src[k] ?? "";
      }
      for (const k of serviceRequired) {
        service[k] = src[k] ?? "";
      }

      const subjectKeys = new Set(["mainId", "mainLicence", "unitName", "natureName", "leaderName", "updateRecordTime"]);
      const serviceKeys = new Set([
        "serviceId", "serviceLicence", "serviceName", "contentTypeName", "accessName",
        "appName", "appVersion", "appStore", "miniProgramName", "miniName", "fastAppName",
        "limitAccess", "domain", "domainId", "serviceType"
      ]);

      for (const [k, v] of Object.entries(src)) {
        if (subjectKeys.has(k) || k.startsWith("main")) {
          if (!isEmpty(v)) subject[k] = v;
        } else if (serviceKeys.has(k) || k.startsWith("service") || k.startsWith("domain")) {
          if (!isEmpty(v)) service[k] = v;
        } else if (!isEmpty(v)) {
          other[k] = v;
        }
      }
      return { subject, service, other, subjectRequired, serviceRequired };
    }

    function renderKVTbody(target, obj, alwaysKeys = []) {
      target.innerHTML = "";
      const keys = [...new Set([...alwaysKeys, ...Object.keys(obj)])];
      if (!keys.length) return false;
      for (const k of keys) {
        const val = obj[k];
        if (!alwaysKeys.includes(k) && isEmpty(val)) continue;
        const tr = document.createElement("tr");
        tr.innerHTML = `<th>${esc(toDisplayKey(k))}</th><td>${esc(isEmpty(val) ? "-" : val)}</td>`;
        target.appendChild(tr);
      }
      return target.children.length > 0;
    }

    function showDetail(row) {
      detailCard.classList.remove("hidden");
      const rec = row.record || {};
      detailHint.textContent = `查询词：${row.query}  |  服务备案号：${rec.serviceLicence || "-"}  |  主办单位：${rec.unitName || "-"}`;
      const sec = splitSections(rec);
      subjectBlock.classList.toggle("hidden", !renderKVTbody(subjectBody, sec.subject, sec.subjectRequired));
      serviceBlock.classList.toggle("hidden", !renderKVTbody(serviceBody, sec.service, sec.serviceRequired));
      otherBlock.classList.toggle("hidden", !renderKVTbody(otherBody, sec.other));
      detailCard.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function flattenResults(results) {
      const out = [];
      let seq = 1;
      for (const group of results || []) {
        if (!group.ok) {
          out.push({
            seq: seq++,
            query: group.query || "",
            status: "失败",
            error: group.error || "",
            record: null,
          });
          continue;
        }
        const records = group.records || [];
        if (!records.length) {
          out.push({
            seq: seq++,
            query: group.query || "",
            status: "成功(0条)",
            error: "",
            record: {},
          });
          continue;
        }
        for (const rec of records) {
          out.push({
            seq: seq++,
            query: group.query || "",
            status: "成功",
            error: "",
            record: rec || {},
          });
        }
      }
      return out;
    }

    function renderResultTable(rows) {
      resultBody.innerHTML = "";
      rows.forEach((row, idx) => {
        const rec = row.record || {};
        const tr = document.createElement("tr");
        const isFailed = row.status === "失败";
        const statusCls = isFailed ? "bad" : "ok";
        let opHtml = "-";
        if (!isFailed && rec && Object.keys(rec).length > 0) {
          opHtml = `<button class="op-btn" data-idx="${idx}">详情</button>`;
        }
        tr.innerHTML = `
          <td>${row.seq}</td>
          <td>${esc(row.query)}</td>
          <td>${esc(rec.unitName || "")}</td>
          <td>${esc(rec.natureName || "")}</td>
          <td>${esc(rec.serviceLicence || "")}</td>
          <td>${esc(rec.updateRecordTime || "")}</td>
          <td class="${statusCls}">${esc(isFailed ? row.error : row.status)}</td>
          <td>${opHtml}</td>
        `;
        resultBody.appendChild(tr);
      });

      resultBody.querySelectorAll("button[data-idx]").forEach(btn => {
        btn.addEventListener("click", () => {
          const i = Number(btn.getAttribute("data-idx"));
          showDetail(rows[i]);
        });
      });
    }

    runBtn.onclick = async () => {
      const keywords = lines(document.getElementById("keywords").value);
      if (!keywords.length) {
        statusEl.textContent = "请先输入查询词。";
        statusEl.className = "status bad";
        return;
      }

      runBtn.disabled = true;
      csvBtn.disabled = true;
      statusEl.textContent = "查询中...";
      statusEl.className = "status";
      resultBody.innerHTML = "";
      detailCard.classList.add("hidden");
      lastResults = [];
      flatRows = [];

      const payload = {
        keywords,
        service_type: Number(document.getElementById("serviceType").value),
        retries: Number(document.getElementById("retries").value),
        transport: document.getElementById("transport").value,
        delay_sec: Number(document.getElementById("delaySec").value),
      };

      try {
        const resp = await fetch("/api/batch_query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "请求失败");

        lastResults = data.results || [];
        flatRows = flattenResults(lastResults);
        renderResultTable(flatRows);

        const okCount = lastResults.filter(x => x.ok).length;
        statusEl.textContent = `完成：${okCount}/${lastResults.length} 查询成功`;
        statusEl.className = okCount === lastResults.length ? "status ok" : "status bad";
        csvBtn.disabled = flatRows.length === 0;
      } catch (e) {
        statusEl.textContent = "失败: " + e.message;
        statusEl.className = "status bad";
      } finally {
        runBtn.disabled = false;
      }
    };

    csvBtn.onclick = async () => {
      if (!lastResults.length) return;
      const resp = await fetch("/api/export_csv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ results: lastResults }),
      });
      if (!resp.ok) return;
      const blob = await resp.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "icp_batch_results.csv";
      a.click();
      URL.revokeObjectURL(a.href);
    };
  </script>
</body>
</html>
"""


class BatchQueryRequest(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    service_type: int = 1
    retries: int = 8
    transport: str = "curl"
    delay_sec: float = 0.2


class ExportRequest(BaseModel):
    results: list[dict[str, Any]] = Field(default_factory=list)


def _is_domain(text: str) -> bool:
    t = text.strip().lower()
    return "." in t and " " not in t


def _merge_detail_into_record(record: dict[str, Any], detail_resp: dict[str, Any]) -> dict[str, Any]:
    merged = dict(record or {})
    params = (detail_resp or {}).get("params")
    if not isinstance(params, dict):
        return merged

    # 常见情况：params 直接是扁平字段
    for k, v in params.items():
        if isinstance(v, (str, int, float, bool)) and v not in ("", None):
            merged[k] = v

    # 兼容嵌套对象：把常见容器里的扁平字段提取出来
    for node_key in ("subjectInfo", "mainInfo", "serviceInfo", "baseInfo", "appInfo", "miniInfo", "fastInfo"):
        node = params.get(node_key)
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, (str, int, float, bool)) and v not in ("", None):
                    merged[k] = v
    return merged


def _query_with_client(client: MiitIcpAutoClient, keyword: str, service_type: int, retries: int) -> dict[str, Any]:
    last_err: Exception | None = None
    used_offset = -1
    for _ in range(max(1, retries)):
        try:
            image_payload = client.get_check_images()
            used_offset, _ = client.verify_slider(image_payload)
            break
        except Exception as exc:
            last_err = exc
            time.sleep(0.3)
    else:
        raise RuntimeError(f"captcha verify failed: {last_err}")

    # 官方 ICP 备案查询前端使用 unitName + serviceType 参数；实测域名关键词也可查到主体信息。
    raw = client.query_company(keyword, service_type)
    params = raw.get("params") or {}
    records = params.get("list") or []

    # APP/小程序/快应用：按官方流程补调 queryDetailByAppAndMiniId，拿到访问名称等详情字段。
    if service_type in (6, 7, 8):
        enriched: list[dict[str, Any]] = []
        for rec in records:
            if not isinstance(rec, dict):
                enriched.append(rec)
                continue
            data_id = rec.get("dataId") or rec.get("serviceId") or rec.get("id")
            if not data_id:
                enriched.append(rec)
                continue
            try:
                detail = client.query_detail_by_app_and_mini_id(data_id, service_type=service_type)
                enriched.append(_merge_detail_into_record(rec, detail))
            except Exception:
                enriched.append(rec)
        records = enriched

    all_keys: set[str] = set()
    for rec in records:
        if isinstance(rec, dict):
            all_keys.update(rec.keys())

    return {
        "query": keyword,
        "query_type": "域名" if _is_domain(keyword) else "主体",
        "ok": True,
        "count": len(records),
        "offset": used_offset,
        "record_columns": sorted(all_keys),
        "records": records,
        "raw": raw,
    }


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return HTML_PAGE


@app.post("/api/batch_query")
def batch_query(req: BatchQueryRequest) -> dict[str, Any]:
    keywords = [x.strip() for x in req.keywords if x and x.strip()]
    if not keywords:
        raise HTTPException(status_code=400, detail="keywords 不能为空")
    if len(keywords) > 100:
        raise HTTPException(status_code=400, detail="单次最多 100 个查询词")
    if req.transport not in ("curl", "requests"):
        raise HTTPException(status_code=400, detail="transport 仅支持 curl/requests")

    results: list[dict[str, Any]] = []
    client = MiitIcpAutoClient(transport=req.transport)
    try:
        client.auth()
    except Exception as exc:
        msg = str(exc)
        if "403" in msg or "Forbidden" in msg:
            raise HTTPException(
                status_code=429,
                detail="当前IP被工信部站点风控临时拦截(HTTP 403)。请稍后重试或更换网络出口。",
            )
        raise HTTPException(status_code=500, detail=f"鉴权失败: {msg}")

    for idx, keyword in enumerate(keywords):
        try:
            row = _query_with_client(
                client=client,
                keyword=keyword,
                service_type=req.service_type,
                retries=req.retries,
            )
        except Exception as exc:
            err = str(exc)
            row = {
                "query": keyword,
                "query_type": "域名" if _is_domain(keyword) else "主体",
                "ok": False,
                "count": 0,
                "record_columns": [],
                "records": [],
                "error": err,
            }
            if "403" in err or "Forbidden" in err:
                row["error"] = "查询被风控拦截(HTTP 403)，建议暂停后重试。"
                results.append(row)
                break
        results.append(row)

        if idx != len(keywords) - 1 and req.delay_sec > 0:
            time.sleep(min(req.delay_sec, 5.0))

    return {"success": True, "results": results}


@app.post("/api/export_csv")
def export_csv(req: ExportRequest) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)

    dynamic_cols: list[str] = []
    seen: set[str] = set()
    for row in req.results:
        for c in row.get("record_columns") or []:
            if c not in seen:
                seen.add(c)
                dynamic_cols.append(c)

    header = ["query", "query_type", "ok", "count"] + dynamic_cols + ["error"]
    writer.writerow(header)

    for row in req.results:
        query = row.get("query", "")
        query_type = row.get("query_type", "")
        ok = row.get("ok", False)
        count = row.get("count", 0)
        error = row.get("error", "")
        records = row.get("records") or []

        if ok and records:
            for rec in records:
                values = [rec.get(c, "") if isinstance(rec, dict) else "" for c in dynamic_cols]
                writer.writerow([query, query_type, ok, count, *values, ""])
        else:
            writer.writerow([query, query_type, ok, count, *([""] * len(dynamic_cols)), error])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="icp_batch_results.csv"'},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("miit_icp_web:app", host="127.0.0.1", port=8000, reload=False)
