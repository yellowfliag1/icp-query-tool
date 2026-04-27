import argparse
import base64
import hashlib
import json
import os
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

import cv2
import ddddocr
import numpy as np
import requests
from PIL import Image
from curl_cffi import requests as curl_requests


BASE_URL = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)


class MiitIcpAutoClient:
    def __init__(self, transport: str = "curl") -> None:
        # 某些环境下会设置无协议代理(如 127.0.0.1:7897)，会让 requests/selenium 直接报错。
        for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
            val = os.environ.get(key, "")
            if val and "://" not in val:
                os.environ.pop(key, None)
        os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

        self.transport = transport
        if transport == "curl":
            self.session = curl_requests.Session(impersonate="chrome124")
        else:
            self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://beian.miit.gov.cn",
                "Referer": "https://beian.miit.gov.cn/",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        self.token = ""
        self.uuid = ""
        self.sign = ""
        self.rci = ""
        self._slide = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)

    @staticmethod
    def _auth_key(account: str, secret: str, ts_ms: int) -> str:
        return hashlib.md5(f"{account}{secret}{ts_ms}".encode("utf-8")).hexdigest()

    def auth(self, account: str = "test", secret: str = "test") -> str:
        ts_ms = int(time.time() * 1000)
        payload = {"authKey": self._auth_key(account, secret, ts_ms), "timeStamp": ts_ms}
        resp = self.session.post(
            BASE_URL + "auth",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        if resp.status_code == 403:
            raise RuntimeError("HTTP 403 Forbidden: auth被风控拦截，请稍后重试或更换网络出口")
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"auth failed: {data}")
        params = data.get("params") or {}
        # JS 中最终用于请求头 token 的返回值是 params.token，
        # bussiness 仅用于本地缓存字段。
        req_token = params.get("token") or params.get("bussiness")
        if not req_token:
            raise RuntimeError(f"auth response missing token: {data}")
        self.token = req_token
        self.session.headers["token"] = req_token
        return req_token

    def get_check_images(self, client_uid: str | None = None) -> dict[str, Any]:
        if not self.token:
            self.auth()
        if not client_uid:
            client_uid = str(uuid.uuid4())
        resp = self.session.post(
            BASE_URL + "image/getCheckImagePoint",
            json={"clientUid": client_uid},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        params = data.get("params") or {}
        self.uuid = params.get("uuid", "")
        if not self.uuid:
            raise RuntimeError(f"getCheckImagePoint failed: {data}")
        return data

    def _calc_offset(self, big_img: bytes, small_img: bytes) -> int:
        candidates: list[int] = []

        # 1) ddddocr 候选
        for simple_target in (False, True):
            try:
                result = self._slide.slide_match(
                    target_bytes=small_img,
                    background_bytes=big_img,
                    simple_target=simple_target,
                )
                target = result.get("target")
                if isinstance(target, list) and len(target) >= 1:
                    x = int(target[0])
                    if 1 <= x <= 435:
                        candidates.append(x)
            except Exception:
                pass

        # 2) OpenCV 掩码模板匹配（一次命中率更高）
        cv_x: int | None = None
        try:
            big_gray = cv2.imdecode(np.frombuffer(big_img, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
            small_rgba = cv2.imdecode(np.frombuffer(small_img, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if big_gray is not None and small_rgba is not None and len(small_rgba.shape) == 3 and small_rgba.shape[2] == 4:
                small_gray = cv2.cvtColor(small_rgba[:, :, :3], cv2.COLOR_BGR2GRAY)
                alpha_mask = small_rgba[:, :, 3]
                res = cv2.matchTemplate(big_gray, small_gray, cv2.TM_CCORR_NORMED, mask=alpha_mask)
                _, _, _, max_loc = cv2.minMaxLoc(res)
                cv_x = int(max_loc[0])
                if 1 <= cv_x <= 435:
                    candidates.append(cv_x)
        except Exception:
            pass

        # 3) 透明边裁剪后再次 ddddocr，作为补偿候选
        try:
            rgba = Image.open(BytesIO(small_img)).convert("RGBA")
            alpha = np.array(rgba)[:, :, 3]
            ys, xs = np.where(alpha > 8)
            if len(xs) > 0 and len(ys) > 0:
                left, top, right, bottom = xs.min(), ys.min(), xs.max(), ys.max()
                cropped = rgba.crop((left, top, right + 1, bottom + 1))
                buf = BytesIO()
                cropped.save(buf, format="PNG")
                result = self._slide.slide_match(
                    target_bytes=buf.getvalue(),
                    background_bytes=big_img,
                    simple_target=True,
                )
                target = result.get("target")
                if isinstance(target, list) and len(target) >= 1:
                    x = int(target[0])
                    if 1 <= x <= 435:
                        candidates.append(x)
        except Exception:
            pass

        if not candidates:
            raise RuntimeError("failed to compute slider offset by ddddocr/opencv")

        # 去重后按与 cv_x 的接近程度排序；若无 cv_x，则优先较大的候选（经验上更稳定）
        uniq = sorted(set(candidates))
        if cv_x is not None:
            uniq.sort(key=lambda v: abs(v - cv_x))
            return uniq[0]
        return sorted(uniq, reverse=True)[0]

    def verify_slider(self, image_payload: dict[str, Any]) -> tuple[int, str]:
        params = image_payload.get("params") or {}
        big_b64 = params.get("bigImage")
        small_b64 = params.get("smallImage")
        if not big_b64 or not small_b64:
            raise RuntimeError(f"captcha image missing: {image_payload}")

        big_img = base64.b64decode(big_b64)
        small_img = base64.b64decode(small_b64)
        offset = self._calc_offset(big_img, small_img)

        resp = self.session.post(
            BASE_URL + "image/checkImage",
            json={"key": self.uuid, "value": str(offset)},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(f"checkImage failed, offset={offset}, resp={data}")

        params2 = data.get("params")
        if isinstance(params2, dict):
            self.sign = params2.get("sign", "")
        else:
            self.sign = params2 or ""
        if not self.sign:
            raise RuntimeError(f"checkImage success but sign missing: {data}")
        return offset, self.sign

    def query_company(
        self,
        company: str,
        service_type: int = 1,
        page_num: int | str | None = None,
        page_size: int | str | None = None,
    ) -> dict[str, Any]:
        if not self.uuid or not self.sign:
            raise RuntimeError("uuid/sign missing, verify slider first")
        headers = {"uuid": self.uuid, "sign": self.sign}
        body: dict[str, Any] = {"unitName": company, "serviceType": service_type}
        body["pageNum"] = "" if page_num in (None, "") else int(page_num)
        body["pageSize"] = "" if page_size in (None, "") else int(page_size)
        resp = self.session.post(
            BASE_URL + "icpAbbreviateInfo/queryByCondition",
            json=body,
            headers=headers,
            timeout=20,
        )
        if resp.status_code == 403:
            waf = "X-Via-JSL" in resp.headers
            body_text = resp.text[:220].replace("\n", " ")
            if waf:
                raise RuntimeError(
                    "查询接口被网站风控拦截(HTTP 403, X-Via-JSL)。"
                    "这不是 company 参数错误，而是非浏览器请求被拦截。"
                    f"响应片段: {body_text}"
                )
            raise RuntimeError(f"query http 403: {body_text}")

        if resp.status_code != 200:
            body_text = resp.text[:220].replace("\n", " ")
            raise RuntimeError(f"query http {resp.status_code}: {body_text}")

        data = resp.json()
        if data.get("success") or data.get("code") == 200:
            self.rci = resp.headers.get("rci", "") or self.rci
            return data
        snippet = json.dumps(data, ensure_ascii=False)[:400]
        raise RuntimeError(f"query business failed: {snippet}")

    @staticmethod
    def _to_int(v: Any, default: int) -> int:
        try:
            return int(v)
        except Exception:
            return default

    def query_company_all(
        self,
        company: str,
        service_type: int = 1,
        page_size: int = 10,
        max_pages: int = 2000,
    ) -> dict[str, Any]:
        # 同一会话 token + uuid + sign 连续翻页，避免不同 token 下顺序漂移。
        first = self.query_company(company, service_type, page_num=1, page_size=page_size)
        first_params = first.get("params") or {}
        first_list = first_params.get("list") or []
        all_records: list[Any] = list(first_list) if isinstance(first_list, list) else []

        total = self._to_int(first_params.get("total"), len(all_records))
        pages = max(1, self._to_int(first_params.get("pages"), 1))
        current_page = max(1, self._to_int(first_params.get("pageNum"), 1))
        limit_pages = max(1, max_pages)
        target_pages = pages
        if target_pages > limit_pages:
            target_pages = limit_pages

        # 先按接口给出的 pages 翻页；若不可靠，再用 total/空页兜底。
        p = current_page + 1
        while p <= target_pages:
            page_data = self.query_company(company, service_type, page_num=p, page_size=page_size)
            page_params = page_data.get("params") or {}
            page_list = page_params.get("list") or []
            before = len(all_records)
            if isinstance(page_list, list):
                all_records.extend(page_list)
            after = len(all_records)
            if after >= total:
                p += 1
                break
            if not page_list or after == before:
                p += 1
                break
            p += 1

        # fallback: 某些场景 pages/nextPage 异常，按 total 继续探测后续页。
        while len(all_records) < total and p <= limit_pages:
            page_data = self.query_company(company, service_type, page_num=p, page_size=page_size)
            page_params = page_data.get("params") or {}
            page_list = page_params.get("list") or []
            before = len(all_records)
            if isinstance(page_list, list):
                all_records.extend(page_list)
            after = len(all_records)
            if not page_list or after == before:
                break
            p += 1

        merged = dict(first)
        merged_params = dict(first_params)
        merged_params["list"] = all_records
        merged_params["size"] = len(all_records)
        merged_params["total"] = total
        merged_params["pageNum"] = 1
        merged_params["pageSize"] = page_size
        merged_params["pages"] = max(1, (len(all_records) + max(1, page_size) - 1) // max(1, page_size))
        merged_params["startRow"] = 0
        merged_params["endRow"] = len(all_records)
        merged_params["hasNextPage"] = False
        merged_params["nextPage"] = 0
        merged_params["hasPreviousPage"] = False
        merged_params["prePage"] = 0
        merged["params"] = merged_params
        return merged

    def query_detail_by_app_and_mini_id(self, data_id: int | str, service_type: int | None = None) -> dict[str, Any]:
        if not self.uuid or not self.sign:
            raise RuntimeError("uuid/sign missing, verify slider first")
        if not data_id:
            raise RuntimeError("data_id is required")

        headers = {"uuid": self.uuid, "sign": self.sign}
        if self.rci:
            headers["rci"] = self.rci

        # 线上接口不同时间版本存在参数名差异，按候选体依次尝试。
        payloads: list[dict[str, Any]] = [
            {"appAndMiniId": data_id},
            {"id": data_id},
            {"dataId": data_id},
        ]
        if service_type is not None:
            payloads.extend(
                [
                    {"appAndMiniId": data_id, "serviceType": service_type},
                    {"id": data_id, "serviceType": service_type},
                    {"dataId": data_id, "serviceType": service_type},
                ]
            )

        last_error = ""
        for body in payloads:
            try:
                resp = self.session.post(
                    BASE_URL + "icpAbbreviateInfo/queryDetailByAppAndMiniId",
                    json=body,
                    headers=headers,
                    timeout=20,
                )
                if resp.status_code == 403:
                    raise RuntimeError("HTTP 403 Forbidden: detail被风控拦截")
                resp.raise_for_status()
                data = resp.json()
                if data.get("success") or data.get("code") == 200:
                    return data
                last_error = f"code={data.get('code')} msg={data.get('msg')}"
            except Exception as exc:
                last_error = str(exc)
                continue

        raise RuntimeError(f"queryDetailByAppAndMiniId failed: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="??????? ICP ???????/???")
    parser.add_argument("query", nargs="?", help="?????????????")
    parser.add_argument("--company", default="", help="???????????")
    parser.add_argument("--input", default="", help="??txt?????????????")
    parser.add_argument("--output", default="", help="????json????????")
    parser.add_argument("--service-type", type=int, default=1, help="1=??, 6=APP, 7=???, 8=???")
    parser.add_argument("--page-size", type=int, default=10, help="??????")
    parser.add_argument("--max-pages", type=int, default=2000, help="????????????")
    parser.add_argument("--retries", type=int, default=5, help="???????")
    parser.add_argument("--manual-offset", type=int, default=-1, help="???????????")
    parser.add_argument("--transport", choices=["curl", "requests"], default="curl", help="????")
    args = parser.parse_args()

    def run_one(query_word: str) -> dict[str, Any]:
        client = MiitIcpAutoClient(transport=args.transport)
        client.auth()

        last_err: Exception | None = None
        used_offset = -1
        if args.manual_offset >= 0:
            images = client.get_check_images(client_uid=str(uuid.uuid4()))
            client.uuid = (images.get("params") or {}).get("uuid", "")
            used_offset = int(args.manual_offset)
            resp = client.session.post(
                BASE_URL + "image/checkImage",
                json={"key": client.uuid, "value": str(used_offset)},
                timeout=20,
            )
            data = resp.json()
            if not data.get("success"):
                raise RuntimeError(f"manual offset checkImage failed: {data}")
            params = data.get("params")
            client.sign = params.get("sign", "") if isinstance(params, dict) else (params or "")
            if not client.sign:
                raise RuntimeError(f"manual offset sign missing: {data}")
        else:
            for _ in range(max(1, args.retries)):
                try:
                    images = client.get_check_images(client_uid=str(uuid.uuid4()))
                    used_offset, _ = client.verify_slider(images)
                    break
                except Exception as exc:
                    last_err = exc
                    time.sleep(0.4)
            else:
                raise RuntimeError(f"captcha verify failed after retries: {last_err}")

        result = client.query_company_all(
            query_word,
            service_type=args.service_type,
            page_size=max(1, args.page_size),
            max_pages=max(1, args.max_pages),
        )
        return {"query": query_word, "offset": used_offset, "ok": True, "result": result}

    if args.input:
        if args.manual_offset >= 0:
            parser.error("????(--input)??? --manual-offset")
        input_path = Path(args.input)
        if not input_path.exists():
            parser.error(f"input ?????: {input_path}")
        queries = [line.strip() for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not queries:
            parser.error("input ?????????")

        all_results: list[dict[str, Any]] = []
        for idx2, q in enumerate(queries, start=1):
            try:
                row = run_one(q)
                print(f"[{idx2}/{len(queries)}] OK: {q} (offset={row['offset']})")
            except Exception as exc:
                row = {"query": q, "ok": False, "error": str(exc)}
                print(f"[{idx2}/{len(queries)}] FAIL: {q} -> {exc}")
            all_results.append(row)

        text_out = json.dumps(all_results, ensure_ascii=False, indent=2)
        if args.output:
            out_path = Path(args.output)
            out_path.write_text(text_out, encoding="utf-8")
            print(f"[+] ???????: {out_path}")
        else:
            print(text_out)
        return

    query = (args.query or args.company or "").strip()
    if not query:
        parser.error("?????????? --input ????")

    one = run_one(query)
    print(f"[+] captcha offset = {one['offset']}")
    print(json.dumps(one["result"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
