#!/usr/bin/env bash
set -uo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rail_mode=false
failures=0
warnings=0

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--rail" ) ]]; then
  echo "用法：$0 [--rail]" >&2
  exit 2
fi
if [[ $# -eq 1 ]]; then
  rail_mode=true
fi

pass() {
  printf '通过  %s\n' "$1"
}

warn() {
  printf '提醒  %s\n' "$1"
  warnings=$((warnings + 1))
}

fail() {
  printf '失败  %s\n' "$1"
  failures=$((failures + 1))
}

version_at_least() {
  local version="${1#v}"
  local required_major="$2"
  local required_minor="$3"
  local major="${version%%.*}"
  local remainder="${version#*.}"
  local minor="${remainder%%.*}"

  [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]] || return 1
  (( major > required_major || (major == required_major && minor >= required_minor) ))
}

require_command() {
  local command_name="$1"
  local purpose="$2"
  if command -v "$command_name" >/dev/null 2>&1; then
    pass "${command_name}：${purpose}"
  else
    fail "缺少 ${command_name}：${purpose}"
  fi
}

echo "Transit2GPX 环境检查"
echo "项目：$project_dir"
echo

if [[ "$(uname -s)" == "Darwin" ]]; then
  pass "macOS：受支持的 POSIX 运行平台"
else
  warn "当前系统为 $(uname -s)；此脚本面向 macOS，Windows 请使用 transit2gpx.ps1"
fi

if command -v uv >/dev/null 2>&1; then
  uv_version="$(uv --version 2>/dev/null | awk '{print $2}')"
  if version_at_least "$uv_version" 0 9; then
    pass "uv ${uv_version}（要求 0.9+）"
  else
    fail "uv ${uv_version:-未知版本}；要求 0.9+"
  fi
else
  fail "缺少 uv 0.9+"
fi

if command -v node >/dev/null 2>&1; then
  node_version="$(node --version 2>/dev/null)"
  if version_at_least "$node_version" 22 0; then
    pass "Node.js ${node_version}（要求 22+）"
  else
    fail "Node.js ${node_version:-未知版本}；要求 22+"
  fi
else
  fail "缺少 Node.js 22+"
fi

if command -v npm >/dev/null 2>&1; then
  npm_version="$(npm --version 2>/dev/null)"
  if version_at_least "$npm_version" 10 0; then
    pass "npm ${npm_version}（要求 10+）"
  else
    fail "npm ${npm_version:-未知版本}；要求 10+"
  fi
else
  fail "缺少 npm 10+"
fi

if [[ -x "$project_dir/backend/.venv/bin/python" ]]; then
  pass "后端依赖已安装"
else
  warn "尚未发现 backend/.venv；首次运行前执行 make setup"
fi
if [[ -d "$project_dir/frontend/node_modules" ]]; then
  pass "前端依赖已安装"
else
  warn "尚未发现 frontend/node_modules；首次运行前执行 make setup"
fi

if [[ "$rail_mode" == true ]]; then
  echo
  echo "铁路附加检查"
  require_command git "获取固定版本的 OpenRailRouting/GraphHopper"
  require_command curl "下载 Maven 和 Geofabrik PBF"
  require_command tar "解压 Maven"
  require_command shasum "校验下载与图身份"
  require_command patch "应用 sidecar 元数据兼容补丁"
  require_command python3 "读取 graph metadata"

  java_bin=""
  if [[ -n "${RAIL_JAVA_HOME:-}" ]]; then
    if [[ -x "$RAIL_JAVA_HOME/bin/java" ]]; then
      java_bin="$RAIL_JAVA_HOME/bin/java"
    else
      fail "RAIL_JAVA_HOME 不包含可执行的 bin/java：$RAIL_JAVA_HOME"
    fi
  elif command -v java >/dev/null 2>&1; then
    java_bin="$(command -v java)"
  else
    fail "缺少 Java 17+；Java 21 是当前验证基线"
  fi

  if [[ -n "$java_bin" ]]; then
    java_version="$("$java_bin" -XshowSettings:properties -version 2>&1 | awk -F'= ' '/java.specification.version/ {print $2; exit}')"
    java_major="${java_version%%.*}"
    if [[ "$java_major" =~ ^[0-9]+$ ]] && (( java_major >= 17 )); then
      pass "Java ${java_version}（${java_bin}；要求 17+，验证基线为 21）"
      if (( java_major != 21 )); then
        warn "当前 Java 不是验证基线 21；如遇构建差异，请设置 RAIL_JAVA_HOME"
      fi
    else
      fail "Java ${java_version:-未知版本}；铁路要求 17+"
    fi
  fi

  if [[ -x "$project_dir/backend/.venv/bin/python" ]] && \
    "$project_dir/backend/.venv/bin/python" -c 'import osmium' >/dev/null 2>&1; then
    pass "Python osmium：可合并区域 PBF"
  else
    warn "尚不能导入 Python osmium；执行 make setup 后再检查"
  fi

  available_kib="$(df -Pk "$project_dir" | awk 'NR == 2 {print $4}')"
  if [[ "$available_kib" =~ ^[0-9]+$ ]]; then
    available_gib=$((available_kib / 1024 / 1024))
    if (( available_gib >= 5 )); then
      pass "可用磁盘约 ${available_gib} GiB（全国图建议至少 5 GiB）"
    elif (( available_gib >= 3 )); then
      warn "可用磁盘约 ${available_gib} GiB：可尝试长三角图，全国图建议至少 5 GiB"
    else
      fail "可用磁盘约 ${available_gib} GiB；长三角图建议至少 3 GiB"
    fi
  else
    warn "无法读取可用磁盘空间"
  fi

  rail_work_dir="${RAIL_WORK_DIR:-$project_dir/data/rail-routing}"
  rail_graph_root="${RAIL_GRAPH_ROOT:-$rail_work_dir/graphs}"
  if [[ -f "$rail_work_dir/dist/openrailrouting.jar" ]]; then
    pass "sidecar JAR 已构建"
  else
    warn "sidecar JAR 尚未构建；首次使用执行 make rail-bootstrap"
  fi
  if [[ -L "$rail_graph_root/active" && ! -e "$rail_graph_root/active.json" ]]; then
    pass "已激活铁路图：$(readlink "$rail_graph_root/active")"
  elif [[ -f "$rail_graph_root/active.json" && ! -e "$rail_graph_root/active" ]]; then
    active_version="$(python3 - "$rail_graph_root/active.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("graph_version", "invalid"))
PY
)"
    pass "已激活铁路图：$active_version"
  else
    warn "尚未发现 active 铁路图；完成构建和固定样本验证后再激活"
  fi
fi

echo
if (( failures > 0 )); then
  printf '检查完成：%d 项失败，%d 项提醒。\n' "$failures" "$warnings"
  exit 1
fi
printf '检查完成：无失败，%d 项提醒。\n' "$warnings"
