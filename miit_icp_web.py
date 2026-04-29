import csv
import io
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

from miit_icp_auto_query import MiitIcpAutoClient


app = FastAPI(title="MIIT ICP Query Web")
QUERY_SESSION_TTL = 15 * 60
QUERY_SESSIONS: dict[str, dict[str, Any]] = {}


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
    .pager { margin-top: 10px; display: flex; gap: 8px; align-items: center; }
    .pager button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--text);
      border-radius: 4px;
      padding: 4px 10px;
      cursor: pointer;
    }
    .pager button:disabled { opacity: .5; cursor: not-allowed; }
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
          <button id="runBtn" type="button" class="btn" onclick="window.__manualRun && window.__manualRun()">搜索</button>
          <button id="csvBtn" type="button" class="btn-alt" onclick="window.__manualExport && window.__manualExport()" disabled>导出CSV</button>
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
        <div id="pager" class="pager hidden"></div>
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
    const pagerEl = document.getElementById("pager");
    const detailCard = document.getElementById("detailCard");
    const detailHint = document.getElementById("detailHint");
    const subjectBlock = document.getElementById("subjectBlock");
    const serviceBlock = document.getElementById("serviceBlock");
    const otherBlock = document.getElementById("otherBlock");
    const subjectBody = document.getElementById("subjectBody");
    const serviceBody = document.getElementById("serviceBody");
    const otherBody = document.getElementById("otherBody");

    let lastResults = [];
    let localRows = [];
    let localPage = 1;
    const localPageSize = 10;

    let remoteSessionId = "";
    let remoteKeyword = "";
    let remotePage = 1;
    let remotePages = 1;
    let remoteTotal = 0;
    let remotePageSize = 10;
    let loading = false;
    let remotePageRecords = {};

    const labelMap = {
      domain: "Domain",
      domainId: "Domain ID",
      unitName: "Host Unit",
      natureName: "Entity Type",
      leaderName: "Owner",
      mainLicence: "ICP Main License",
      serviceLicence: "Service License",
      serviceName: "Access Name",
      contentTypeName: "Service Name",
      accessName: "Access Name",
      appName: "App Name",
      miniProgramName: "Mini Program",
      fastAppName: "Quick App",
      limitAccess: "Pre-approval",
      updateRecordTime: "Review Time",
    };

    function esc(v) {
      return String(v == null ? "" : v)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function splitLines(v) {
      return String(v || "")
        .replaceAll(String.fromCharCode(13), "")
        .split(String.fromCharCode(10))
        .map(s => s.trim())
        .filter(Boolean);
    }

    function isEmpty(v) {
      return v === null || v === undefined || v === "" ||
             (Array.isArray(v) && v.length === 0) ||
             (typeof v === "object" && !Array.isArray(v) && Object.keys(v).length === 0);
    }

    function setStatus(text, bad) {
      statusEl.textContent = text;
      statusEl.className = bad ? "status bad" : "status ok";
    }

    function renderKV(target, obj) {
      target.innerHTML = "";
      const keys = Object.keys(obj || {});
      for (const k of keys) {
        const val = obj[k];
        if (isEmpty(val)) continue;
        const tr = document.createElement("tr");
        tr.innerHTML = "<th>" + esc(labelMap[k] || k) + "</th><td>" + esc(val) + "</td>";
        target.appendChild(tr);
      }
      return target.children.length > 0;
    }

    function showDetail(row) {
      const rec = row.record || {};
      detailHint.textContent = "Query: " + row.query + " | Service License: " + (rec.serviceLicence || "-") + " | Unit: " + (rec.unitName || "-");
      const subject = {
        mainLicence: rec.mainLicence || "",
        updateRecordTime: rec.updateRecordTime || "",
        unitName: rec.unitName || "",
        natureName: rec.natureName || "",
        leaderName: rec.leaderName || "",
      };
      const service = {
        serviceLicence: rec.serviceLicence || "",
        serviceName: rec.serviceName || "",
        contentTypeName: rec.contentTypeName || "",
        accessName: rec.accessName || "",
        appName: rec.appName || "",
        miniProgramName: rec.miniProgramName || "",
        fastAppName: rec.fastAppName || "",
        limitAccess: rec.limitAccess || "",
        domain: rec.domain || "",
      };
      const other = {};
      for (const [k, v] of Object.entries(rec)) {
        if (!(k in subject) && !(k in service) && !isEmpty(v)) other[k] = v;
      }
      subjectBlock.classList.toggle("hidden", !renderKV(subjectBody, subject));
      serviceBlock.classList.toggle("hidden", !renderKV(serviceBody, service));
      otherBlock.classList.toggle("hidden", !renderKV(otherBody, other));
      detailCard.classList.remove("hidden");
      detailCard.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function renderRows(rows) {
      resultBody.innerHTML = "";
      rows.forEach((row, i) => {
        const rec = row.record || {};
        const failed = row.status === "Failed";
        const tr = document.createElement("tr");
        tr.innerHTML = "<td>" + row.seq + "</td>" +
          "<td>" + esc(row.query) + "</td>" +
          "<td>" + esc(rec.unitName || "") + "</td>" +
          "<td>" + esc(rec.natureName || "") + "</td>" +
          "<td>" + esc(rec.serviceLicence || "") + "</td>" +
          "<td>" + esc(rec.updateRecordTime || "") + "</td>" +
          "<td class='" + (failed ? "bad" : "ok") + "'>" + esc(failed ? (row.error || "Failed") : "Success") + "</td>" +
          "<td>" + ((!failed && rec && Object.keys(rec).length > 0) ? ("<button type='button' class='op-btn' data-i='" + i + "'>Detail</button>") : "-") + "</td>";
        resultBody.appendChild(tr);
      });
      resultBody.querySelectorAll("button[data-i]").forEach(btn => {
        btn.addEventListener("click", function() {
          const idx = Number(btn.getAttribute("data-i"));
          showDetail(rows[idx]);
        });
      });
    }

    function renderLocalPager() {
      const total = localRows.length;
      if (!total) {
        pagerEl.classList.add("hidden");
        pagerEl.innerHTML = "";
        resultBody.innerHTML = "";
        return;
      }
      const pages = Math.max(1, Math.ceil(total / localPageSize));
      if (localPage < 1) localPage = 1;
      if (localPage > pages) localPage = pages;
      const start = (localPage - 1) * localPageSize;
      const rows = localRows.slice(start, start + localPageSize);
      renderRows(rows);

      pagerEl.classList.remove("hidden");
      pagerEl.innerHTML = "<button type='button' id='pgPrev' " + (localPage <= 1 ? "disabled" : "") + ">Prev</button>" +
                         "<span>Page " + localPage + "/" + pages + ", total " + total + "</span>" +
                         "<button type='button' id='pgNext' " + (localPage >= pages ? "disabled" : "") + ">Prev</button>";
      document.getElementById("pgPrev").onclick = function() { localPage -= 1; renderLocalPager(); };
      document.getElementById("pgNext").onclick = function() { localPage += 1; renderLocalPager(); };
    }

    function mapRemote(records, pageNum, pageSize) {
      const base = (Math.max(1, pageNum) - 1) * Math.max(1, pageSize);
      return (records || []).map((rec, idx) => ({
        seq: base + idx + 1,
        query: remoteKeyword,
        status: "Success",
        error: "",
        record: rec || {},
      }));
    }

    function renderRemotePager() {
      pagerEl.classList.remove("hidden");
      pagerEl.innerHTML = "<button type='button' id='pgPrev' " + ((remotePage <= 1 || loading) ? "disabled" : "") + ">Prev</button>" +
                         "<span>Page " + remotePage + "/" + remotePages + ", total " + remoteTotal + "</span>" +
                          "<button type='button' id='pgNext' " + ((remotePage >= remotePages || loading) ? "disabled" : "") + ">Next</button>";
      document.getElementById("pgPrev").onclick = async function() { if (remotePage > 1) await loadRemotePage(remotePage - 1); };
      document.getElementById("pgNext").onclick = async function() { if (remotePage < remotePages) await loadRemotePage(remotePage + 1); };
    }

    function refreshRemoteExportRows() {
      const pageNums = Object.keys(remotePageRecords)
        .map(x => Number(x))
        .filter(x => Number.isFinite(x))
        .sort((a, b) => a - b);
      const merged = [];
      for (const pn of pageNums) {
        const arr = Array.isArray(remotePageRecords[pn]) ? remotePageRecords[pn] : [];
        for (const rec of arr) merged.push(rec);
      }
      lastResults = [{
        query: remoteKeyword,
        query_type: remoteKeyword.includes(".") ? "domain" : "subject",
        ok: true,
        count: merged.length,
        record_columns: [],
        records: merged
      }];
      csvBtn.disabled = merged.length === 0;
    }

    async function loadRemotePage(pageNum) {
      if (!remoteSessionId || loading) return;
      loading = true;
      setStatus("Loading page " + pageNum + "...", false);
      renderRemotePager();
      try {
        const resp = await fetch("/api/query_page", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: remoteSessionId, page_num: pageNum })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "Query failed");
        remotePage = Number(data.pageNum || pageNum || 1);
        remotePages = Math.max(1, Number(data.pages || 1));
        remoteTotal = Math.max(0, Number(data.total || 0));
        const currentRecords = Array.isArray(data.records) ? data.records : [];
        remotePageRecords[remotePage] = currentRecords;
        refreshRemoteExportRows();
        const rows = mapRemote(currentRecords, remotePage, Number(data.pageSize || remotePageSize || 10));
        renderRows(rows);
        setStatus("Loaded page " + remotePage + "/" + remotePages + ", total " + remoteTotal, false);
      } catch (e) {
        setStatus("Page load failed: " + e.message, true);
      } finally {
        loading = false;
        renderRemotePager();
      }
    }

    async function runSearch() {
      const keywords = splitLines(document.getElementById("keywords").value);
      if (!keywords.length) {
        setStatus("Please input keyword", true);
        return;
      }

      runBtn.disabled = true;
      csvBtn.disabled = true;
      setStatus("Searching...", false);
      resultBody.innerHTML = "";
      pagerEl.classList.add("hidden");
      pagerEl.innerHTML = "";
      detailCard.classList.add("hidden");

      lastResults = [];
      localRows = [];
      localPage = 1;
      remoteSessionId = "";
      remoteKeyword = "";
      remotePage = 1;
      remotePages = 1;
      remoteTotal = 0;
      remotePageSize = localPageSize;
      remotePageRecords = {};

      const commonPayload = {
        service_type: Number(document.getElementById("serviceType").value),
        retries: Number(document.getElementById("retries").value),
        transport: document.getElementById("transport").value,
      };

      try {
        if (keywords.length === 1) {
          const resp = await fetch("/api/start_query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ keyword: keywords[0], page_size: localPageSize, ...commonPayload })
          });
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.detail || "Query failed");

          remoteSessionId = data.session_id || "";
          remoteKeyword = keywords[0];
          remotePage = Number(data.pageNum || 1);
          remotePages = Math.max(1, Number(data.pages || 1));
          remoteTotal = Math.max(0, Number(data.total || 0));
          remotePageSize = Math.max(1, Number(data.pageSize || localPageSize));
          const firstRecords = Array.isArray(data.records) ? data.records : [];
          remotePageRecords[remotePage] = firstRecords;
          refreshRemoteExportRows();
          renderRows(mapRemote(firstRecords, remotePage, remotePageSize));
          renderRemotePager();
          setStatus("Loaded page " + remotePage + "/" + remotePages + ", total " + remoteTotal + " (lazy paging)", false);
        } else {
          const delaySec = Number(document.getElementById("delaySec").value);
          const resp = await fetch("/api/batch_query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ keywords, delay_sec: delaySec, ...commonPayload })
          });
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.detail || "Batch query failed");
          lastResults = data.results || [];
          let seq = 1;
          for (const g of lastResults) {
            if (!g.ok) {
              localRows.push({ seq: seq++, query: g.query || "", status: "Success", error: g.error || "", record: null });
              continue;
            }
            const rs = Array.isArray(g.records) ? g.records : [];
            if (!rs.length) {
              localRows.push({ seq: seq++, query: g.query || "", status: "Success", error: "", record: {} });
              continue;
            }
            for (const rec of rs) {
              localRows.push({ seq: seq++, query: g.query || "", status: "Success", error: "", record: rec || {} });
            }
          }
          renderLocalPager();
          const okCount = lastResults.filter(x => x.ok).length;
          setStatus("Done: " + okCount + "/" + lastResults.length + " succeeded", okCount !== lastResults.length);
          csvBtn.disabled = localRows.length === 0;
        }
      } catch (e) {
        setStatus("Failed: " + e.message, true);
      } finally {
        runBtn.disabled = false;
      }
    }

    async function exportCsv() {
      if (!lastResults.length) return;
      const resp = await fetch("/api/export_csv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ results: lastResults })
      });
      if (!resp.ok) return;
      const blob = await resp.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "icp_batch_results.csv";
      a.click();
      URL.revokeObjectURL(a.href);
    }

    window.__manualRun = runSearch;
    window.__manualExport = exportCsv;
    runBtn.addEventListener("click", runSearch);
    csvBtn.addEventListener("click", exportCsv);
  </script>
  <script>
    (function () {
      if (typeof window.__manualRun === "function") return;

      const runBtn = document.getElementById("runBtn");
      const statusEl = document.getElementById("status");
      const resultBody = document.getElementById("resultBody");
      const pagerEl = document.getElementById("pager");
      const keywordsEl = document.getElementById("keywords");
      const serviceTypeEl = document.getElementById("serviceType");
      const retriesEl = document.getElementById("retries");
      const transportEl = document.getElementById("transport");

      if (!runBtn || !statusEl || !resultBody || !pagerEl || !keywordsEl) return;

      let sid = "";
      let page = 1;
      let pages = 1;
      let total = 0;
      let psize = 10;
      let keyword = "";
      let busy = false;

      function setStatus(t, bad) {
        statusEl.textContent = t;
        statusEl.className = bad ? "status bad" : "status ok";
      }

      function esc(v) {
        return String(v == null ? "" : v)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;");
      }

      function renderRows(records, pageNum, pageSize) {
        resultBody.innerHTML = "";
        const base = (Math.max(1, pageNum) - 1) * Math.max(1, pageSize);
        (records || []).forEach((rec, idx) => {
          const tr = document.createElement("tr");
          tr.innerHTML =
            "<td>" + (base + idx + 1) + "</td>" +
            "<td>" + esc(keyword) + "</td>" +
            "<td>" + esc((rec || {}).unitName || "") + "</td>" +
            "<td>" + esc((rec || {}).natureName || "") + "</td>" +
            "<td>" + esc((rec || {}).serviceLicence || "") + "</td>" +
            "<td>" + esc((rec || {}).updateRecordTime || "") + "</td>" +
            "<td class='ok'>成功</td>" +
            "<td>-</td>";
          resultBody.appendChild(tr);
        });
      }

      function renderPager() {
        pagerEl.classList.remove("hidden");
        pagerEl.innerHTML =
          "<button type='button' id='fbPrev' " + ((page <= 1 || busy) ? "disabled" : "") + ">上一页</button>" +
          "<span>第 " + page + "/" + pages + " 页，共 " + total + " 条</span>" +
          "<button type='button' id='fbNext' " + ((page >= pages || busy) ? "disabled" : "") + ">下一页</button>";
        const prev = document.getElementById("fbPrev");
        const next = document.getElementById("fbNext");
        if (prev) prev.onclick = function () { if (page > 1) loadPage(page - 1); };
        if (next) next.onclick = function () { if (page < pages) loadPage(page + 1); };
      }

      async function loadPage(pn) {
        if (!sid || busy) return;
        busy = true;
        setStatus("正在加载第 " + pn + " 页...", false);
        renderPager();
        try {
          const resp = await fetch("/api/query_page", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sid, page_num: pn }),
          });
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.detail || "翻页失败");
          page = Number(data.pageNum || pn || 1);
          pages = Math.max(1, Number(data.pages || 1));
          total = Math.max(0, Number(data.total || 0));
          psize = Math.max(1, Number(data.pageSize || psize || 10));
          renderRows(data.records || [], page, psize);
          setStatus("已加载第 " + page + "/" + pages + " 页，共 " + total + " 条", false);
        } catch (e) {
          setStatus("翻页失败: " + e.message, true);
        } finally {
          busy = false;
          renderPager();
        }
      }

      async function runSearchFallback() {
        if (busy) return;
        const words = String(keywordsEl.value || "")
          .replaceAll(String.fromCharCode(13), "")
          .split(String.fromCharCode(10))
          .map(s => s.trim())
          .filter(Boolean);
        if (!words.length) {
          setStatus("请先输入查询词", true);
          return;
        }
        keyword = words[0];
        page = 1;
        pages = 1;
        total = 0;
        resultBody.innerHTML = "";
        pagerEl.classList.add("hidden");
        pagerEl.innerHTML = "";
        busy = true;
        setStatus("查询中...", false);
        try {
          const resp = await fetch("/api/start_query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              keyword: keyword,
              service_type: Number((serviceTypeEl || {}).value || 1),
              retries: Number((retriesEl || {}).value || 8),
              transport: (transportEl || {}).value || "curl",
              page_size: 10
            }),
          });
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.detail || "查询失败");
          sid = data.session_id || "";
          page = Number(data.pageNum || 1);
          pages = Math.max(1, Number(data.pages || 1));
          total = Math.max(0, Number(data.total || 0));
          psize = Math.max(1, Number(data.pageSize || 10));
          renderRows(data.records || [], page, psize);
          renderPager();
          setStatus("已加载第 " + page + "/" + pages + " 页，共 " + total + " 条", false);
        } catch (e) {
          setStatus("查询失败: " + e.message, true);
        } finally {
          busy = false;
          renderPager();
        }
      }

      window.__manualRun = runSearchFallback;
      runBtn.onclick = runSearchFallback;
    })();
  </script>
</body>
</html>
"""


class BatchQueryRequest(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    service_type: int = 1
    page_size: int = 10
    max_pages: int = 2000
    retries: int = 8
    transport: str = "curl"
    delay_sec: float = 0.2


class ExportRequest(BaseModel):
    results: list[dict[str, Any]] = Field(default_factory=list)


class StartQueryRequest(BaseModel):
    keyword: str
    service_type: int = 1
    retries: int = 8
    transport: str = "curl"
    page_size: int = 10


class QueryPageRequest(BaseModel):
    session_id: str
    page_num: int = 1


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


def _cleanup_query_sessions() -> None:
    now = time.time()
    expired = [
        sid
        for sid, sess in QUERY_SESSIONS.items()
        if now - float(sess.get("updated_at", 0)) > QUERY_SESSION_TTL
    ]
    for sid in expired:
        QUERY_SESSIONS.pop(sid, None)


def _get_query_session(session_id: str) -> dict[str, Any]:
    _cleanup_query_sessions()
    sess = QUERY_SESSIONS.get(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="查询会话不存在或已过期，请重新搜索")
    sess["updated_at"] = time.time()
    return sess


def _enrich_app_records(
    client: MiitIcpAutoClient,
    records: list[Any],
    service_type: int,
) -> list[Any]:
    if service_type not in (6, 7, 8):
        return records
    enriched: list[Any] = []
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
    return enriched


def _fetch_page_with_session(
    sess: dict[str, Any],
    page_num: int,
) -> dict[str, Any]:
    client = sess["client"]
    keyword = sess["keyword"]
    service_type = int(sess["service_type"])
    page_size = int(sess["page_size"])

    raw = client.query_company(
        keyword,
        service_type=service_type,
        page_num=max(1, page_num),
        page_size=max(1, page_size),
    )
    params = raw.get("params") or {}
    records = params.get("list") or []
    if not isinstance(records, list):
        records = []
    records = _enrich_app_records(client, records, service_type)

    all_keys: set[str] = set()
    for rec in records:
        if isinstance(rec, dict):
            all_keys.update(rec.keys())

    return {
        "query": keyword,
        "query_type": "域名" if _is_domain(keyword) else "主体",
        "ok": True,
        "record_columns": sorted(all_keys),
        "records": records,
        "pageNum": int(params.get("pageNum") or page_num or 1),
        "pageSize": int(params.get("pageSize") or page_size),
        "pages": int(params.get("pages") or 1),
        "total": int(params.get("total") or len(records)),
    }


def _query_with_client(
    client: MiitIcpAutoClient,
    keyword: str,
    service_type: int,
    retries: int,
    page_size: int,
    max_pages: int,
) -> dict[str, Any]:
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
    raw = client.query_company_all(
        keyword,
        service_type=service_type,
        page_size=max(1, page_size),
        max_pages=max(1, max_pages),
    )
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
    return HTMLResponse(
        content=HTML_PAGE,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.post("/api/start_query")
def start_query(req: StartQueryRequest) -> dict[str, Any]:
    keyword = (req.keyword or "").strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword 不能为空")
    if req.transport not in ("curl", "requests"):
        raise HTTPException(status_code=400, detail="transport 仅支持 curl/requests")
    if req.page_size <= 0 or req.page_size > 200:
        raise HTTPException(status_code=400, detail="page_size 需在 1~200 之间")

    client = MiitIcpAutoClient(transport=req.transport)
    try:
        client.auth()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"鉴权失败: {exc}")

    last_err: Exception | None = None
    for _ in range(max(1, req.retries)):
        try:
            image_payload = client.get_check_images()
            client.verify_slider(image_payload)
            break
        except Exception as exc:
            last_err = exc
            time.sleep(0.3)
    else:
        raise HTTPException(status_code=500, detail=f"验证码失败: {last_err}")

    session_id = uuid.uuid4().hex
    sess = {
        "client": client,
        "keyword": keyword,
        "service_type": req.service_type,
        "page_size": req.page_size,
        "updated_at": time.time(),
    }
    QUERY_SESSIONS[session_id] = sess
    page_data = _fetch_page_with_session(sess, page_num=1)
    return {"success": True, "session_id": session_id, **page_data}


@app.post("/api/query_page")
def query_page(req: QueryPageRequest) -> dict[str, Any]:
    sess = _get_query_session(req.session_id)
    page_data = _fetch_page_with_session(sess, page_num=max(1, req.page_num))
    return {"success": True, "session_id": req.session_id, **page_data}


@app.post("/api/batch_query")
def batch_query(req: BatchQueryRequest) -> dict[str, Any]:
    keywords = [x.strip() for x in req.keywords if x and x.strip()]
    if not keywords:
        raise HTTPException(status_code=400, detail="keywords 不能为空")
    if len(keywords) > 100:
        raise HTTPException(status_code=400, detail="单次最多 100 个查询词")
    if req.transport not in ("curl", "requests"):
        raise HTTPException(status_code=400, detail="transport 仅支持 curl/requests")
    if req.page_size <= 0 or req.page_size > 200:
        raise HTTPException(status_code=400, detail="page_size 需在 1~200 之间")
    if req.max_pages <= 0 or req.max_pages > 5000:
        raise HTTPException(status_code=400, detail="max_pages 需在 1~5000 之间")

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
                page_size=req.page_size,
                max_pages=req.max_pages,
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
