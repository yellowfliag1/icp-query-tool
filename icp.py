import requests
import hashlib
import time
import json
import base64
import argparse
import os
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, List
from dataclasses import dataclass
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 错误定义
class IllegalRequestError(Exception):
    pass

class TokenExpiredError(Exception):
    pass

class CaptchaMismatchError(Exception):
    pass

@dataclass
class ICPItem:
    service_name: str
    leader_name: str
    nature_name: str
    service_licence: str
    unit_name: str
    update_record_time: str
    service_type: str

class ICPQuery:
    def __init__(self, proxy: Optional[str] = None):
        # 解码URL
        self.referer = base64.b64decode("aHR0cHM6Ly9iZWlhbi5taWl0Lmdvdi5jbi8=").decode()
        self.get_token_url = base64.b64decode("aHR0cHM6Ly9obHdpY3Bmd2MubWlpdC5nb3YuY24vaWNwcHJvamVjdF9xdWVyeS9hcGkvYXV0aA==").decode()
        self.query_url = base64.b64decode("aHR0cHM6Ly9obHdpY3Bmd2MubWlpdC5nb3YuY24vaWNwcHJvamVjdF9xdWVyeS9hcGkvaWNwQWJicmV2aWF0ZUluZm8vcXVlcnlCeUNvbmRpdGlvbi8=").decode()
        
        # 初始化属性
        self.token = None
        self.refresh_token = None
        self.expire_in = 0
        self.sign = "eyJ0eXBlIjozLCJleHREYXRhIjp7InZhZnljb2RlX2ltYWdlX2tleSI6ImJhMjVlZGNjZGNlYjQwYWY4MjNmNzViYmEwODZhYTFkIn0sImUiOjE3NDcxMDg2Mzk5NzJ9.fJZg3jIz-vRYq4pgKdtu38CDC4DW9-SL9t1qUZO4Z3k"
        
        # 设置代理
        self.proxies = None
        if proxy:
            self.proxies = {
                "http": proxy,
                "https": proxy
            }
            print(f"使用代理: {proxy}")
        
        # 设置基础请求头
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.referer,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Cookie": "__jsluid_s=6452684553c30942fcb8cff8d5aa5a5b"
        }

    def set_token_from_remote(self) -> bool:
        """获取认证token"""
        try:
            timestamp = str(int(time.time() * 1000))
            auth_key = hashlib.md5(f"testtest{timestamp}".encode()).hexdigest()
            
            data = {
                "authKey": auth_key,
                "timeStamp": timestamp
            }
            
            # 每次请求都创建新的会话
            session = requests.Session()
            # 禁用连接池
            adapter = HTTPAdapter(pool_connections=0, pool_maxsize=0)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            
            response = session.post(
                self.get_token_url,
                headers=self.headers,
                data=data,
                timeout=10,
                proxies=self.proxies
            )
            
            if response.status_code != 200:
                raise Exception(f"获取token失败，状态码: {response.status_code}")
            
            result = response.json()
            if result.get("code") != 200:
                raise Exception(f"获取token失败: {result.get('msg')}")
            
            self.expire_in = int(timestamp) + result["params"]["expire"]
            self.token = result["params"]["bussiness"]
            self.refresh_token = result["params"]["refresh"]
            return True
            
        except Exception as e:
            print(f"获取token失败: {str(e)}")
            return False

    def query(self, unit_name: str, page_num: int, page_size: int, service_type: str) -> Optional[Dict]:
        """查询ICP备案信息"""
        max_retries = 5  # 最大重试次数
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # 检查token
                if not self.token or time.time() * 1000 >= self.expire_in:
                    if not self.set_token_from_remote():
                        return None
                
                # 设置查询请求头
                headers = self.headers.copy()
                headers["Token"] = self.token
                headers["Sign"] = self.sign
                headers["Content-Type"] = "application/json;charset=UTF-8"
                
                # 查询参数
                data = {
                    "pageNum": page_num,
                    "pageSize": page_size,
                    "unitName": unit_name,
                    "serviceType": service_type
                }
                
                # 每次请求都创建新的会话
                session = requests.Session()
                # 禁用连接池
                adapter = HTTPAdapter(pool_connections=0, pool_maxsize=0)
                session.mount("http://", adapter)
                session.mount("https://", adapter)
                
                response = session.post(
                    self.query_url,
                    headers=headers,
                    json=data,
                    timeout=10,
                    proxies=self.proxies
                )
                
                if response.status_code == 403:
                    print(f"IP 被封禁，正在切换 IP... (第 {retry_count + 1} 次尝试)")
                    retry_count += 1
                    time.sleep(1)  # 等待一秒再重试
                    continue
                
                if response.status_code != 200:
                    raise Exception(f"查询失败，状态码: {response.status_code}")
                
                result = response.json()
                if result.get("code") != 200:
                    error_msg = result.get("msg", "")
                    if "验证码不匹配" in error_msg:
                        raise CaptchaMismatchError(error_msg)
                    elif "token过期" in error_msg:
                        raise TokenExpiredError(error_msg)
                    elif "请求非法" in error_msg:
                        raise IllegalRequestError(error_msg)
                    else:
                        raise Exception(error_msg)
                
                # 处理查询结果
                params = result.get("params", {})
                items = []
                
                for item in params.get("list", []):
                    service_name = item.get("domain") if service_type == "1" else item.get("serviceName")
                    service_type_name = {
                        "1": "网站",
                        "6": "APP",
                        "7": "小程序",
                        "8": "快应用"
                    }.get(service_type, "")
                    
                    icp_item = ICPItem(
                        service_name=service_name,
                        leader_name=item.get("leaderName", ""),
                        nature_name=item.get("natureName", ""),
                        service_licence=item.get("serviceLicence", ""),
                        unit_name=item.get("unitName", ""),
                        update_record_time=item.get("updateRecordTime", ""),
                        service_type=service_type_name
                    )
                    items.append(icp_item)
                
                return {
                    "pageNum": params.get("pageNum", 0),
                    "pageSize": params.get("pageSize", 0),
                    "total": params.get("total", 0),
                    "items": items
                }
                
            except (CaptchaMismatchError, TokenExpiredError, IllegalRequestError) as e:
                print(f"查询失败: {str(e)}")
                return None
            except Exception as e:
                print(f"查询异常: {str(e)}")
                retry_count += 1
                if retry_count < max_retries:
                    print(f"正在重试... (第 {retry_count + 1} 次尝试)")
                    time.sleep(1)  # 等待一秒再重试
                    continue
                return None
        
        print(f"达到最大重试次数 ({max_retries})，查询失败")
        return None

def main():
    # 创建命令行参数解析器
    parser = argparse.ArgumentParser(description='ICP备案信息查询工具')
    parser.add_argument('company_name', type=str, nargs='?', help='要查询的公司名称，多个公司用逗号分隔，如：小米,百度')
    parser.add_argument('--type', type=str, choices=['1', '6', '7', '8'], default='1',
                      help='查询类型（默认为1-网站）：1-网站，6-APP，7-小程序，8-快应用')
    parser.add_argument('-o', '--output', type=str, help='导出结果到指定文件')
    parser.add_argument('-e', '--excel', type=str, help='导出结果到Excel文件')
    parser.add_argument('-f', '--file', type=str, help='从文件读取公司名称列表进行批量查询')
    parser.add_argument('--proxy', type=str, help='指定代理地址，例如：socks5://127.0.0.1:10086')
    
    # 解析命令行参数
    args = parser.parse_args()
    
    # 检查是否提供了公司名称或文件
    if not args.company_name and not args.file:
        parser.error("必须提供公司名称或包含公司名称的文件")
    
    # 创建查询实例
    icp = ICPQuery(proxy=args.proxy)
    
    # 用于存储每个公司的域名
    company_domains = {}
    # 用于存储所有查询结果
    all_results = []
    
    def process_company(company_name):
        nonlocal company_domains, all_results
        
        processed_records = set()  # 用于存储已处理的记录
        total_records = 0
        retry_count = 0
        max_retries = 10  # 最大重试次数
        
        while retry_count < max_retries:
            # 执行查询
            result = icp.query(
                unit_name=company_name,
                page_num=1,  # 始终请求第一页
                page_size=40,  # 固定使用40条记录
                service_type=args.type
            )
            
            if not result:
                print(f"\n查询公司 {company_name} 失败，请检查网络连接或参数是否正确")
                return False
            
            # 第一次查询时打印总记录数
            if not total_records:
                total_records = result['total']
                print(f"\n查询公司：{company_name}")
                print(f"总记录数：{total_records}")
                print("=" * 80)
            
            # 存储当前公司的域名
            if not company_domains.get(company_name):
                company_domains[company_name] = []
            
            # 处理当前页的结果
            new_records = 0  # 记录本页新增的记录数
            for item in result["items"]:
                # 使用备案号和域名组合作为唯一标识
                record_key = f"{item.service_licence}_{item.service_name}"
                
                # 如果记录已经处理过，跳过
                if record_key in processed_records:
                    continue
                
                processed_records.add(record_key)
                new_records += 1
                
                current_index = len(processed_records)
                print(f"\n记录 {current_index}/{total_records}:")
                print(f"单位名称: {item.unit_name}")
                print(f"网站名称: {item.service_name}")
                print(f"备案号: {item.service_licence}")
                print(f"备案类型: {item.service_type}")
                print(f"备案法人: {item.leader_name}")
                print(f"单位性质: {item.nature_name}")
                print(f"审核日期: {item.update_record_time}")
                print("-" * 80)
                
                # 收集域名
                if args.type == '1' and item.service_name:  # 只收集网站类型的域名
                    company_domains[company_name].append(item.service_name)
                
                # 收集结果用于Excel导出
                all_results.append({
                    '公司主体名称': item.unit_name,
                    'ICP备案/许可证号': item.service_licence,
                    '审核通过日期': item.update_record_time,
                    '网站域名': item.service_name if args.type == '1' else ''
                })
            
            # 如果已经获取的记录数达到或超过总记录数，退出
            if len(processed_records) >= total_records:
                break
            
            # 如果本页没有新记录，增加重试计数
            if new_records == 0:
                retry_count += 1
                print(f"\n本次未获取到新记录，重试次数：{retry_count}/{max_retries}")
            else:
                retry_count = 0  # 重置重试计数
            
            # 添加延时，避免请求过快
            time.sleep(1)
        
        if len(processed_records) >= total_records:
            print(f"\n完成查询，共获取 {len(company_domains[company_name])} 条域名记录")
            return True
        else:
            print(f"\n达到最大重试次数，已获取 {len(processed_records)}/{total_records} 条记录")
            return False
    
    # 处理查询
    if args.file:
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                companies = [line.strip() for line in f if line.strip()]
            
            print(f"从文件 {args.file} 中读取到 {len(companies)} 个公司名称")
            
            for company in companies:
                process_company(company)
                
        except Exception as e:
            print(f"读取文件失败：{str(e)}")
    else:
        # 处理逗号分隔的多个公司名称
        companies = [name.strip() for name in args.company_name.split(',') if name.strip()]
        print(f"将查询 {len(companies)} 个公司")
        
        for company in companies:
            process_company(company)
    
    # 导出到Excel
    if args.excel and all_results:
        try:
            # 创建DataFrame
            df = pd.DataFrame(all_results)
            
            # 生成默认文件名（如果未指定）
            if not args.excel.endswith('.xlsx'):
                args.excel = f"{args.excel}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            
            # 导出到Excel
            df.to_excel(args.excel, index=False, engine='openpyxl')
            print(f"\n结果已导出到Excel文件：{args.excel}")
        except Exception as e:
            print(f"\n导出Excel文件失败：{str(e)}")
    
    # 导出到文本文件
    if args.output and company_domains:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(f"ICP备案域名查询结果\n")
                f.write(f"查询时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 80 + "\n\n")
                
                for company, domains in company_domains.items():
                    if domains:  # 只导出有域名的公司
                        f.write(f"公司名称：{company}\n")
                        f.write("域名列表：\n")
                        for domain in domains:
                            f.write(f"{domain}\n")
                        f.write("\n" + "-" * 80 + "\n\n")
            
            print(f"\n域名列表已导出到文件：{args.output}")
        except Exception as e:
            print(f"\n导出文件失败：{str(e)}")
    
    # 打印域名汇总
    print("\n域名汇总：")
    print("=" * 80)
    for company, domains in company_domains.items():
        if domains:  # 只显示有域名的公司
            print(f"\n公司：{company}")
            for domain in domains:
                print(domain)
            print("-" * 80)

if __name__ == "__main__":
    main()
