"""Standalone HTML. All repository data is escaped text, never executable data."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import unicodedata

from .report_validation import validate_report


CSS = """
:root{color-scheme:light;--ink:#202b32;--muted:#5d6b73;--line:#dce3e3;--paper:#f5f7f6;--accent:#176c61}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
main{max-width:1280px;margin:auto;padding:30px 36px 70px}header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line);padding-bottom:20px;gap:20px}
.brand{font-weight:750;letter-spacing:-.5px;font-size:19px}.brand b{background:var(--accent);color:white;border-radius:7px;padding:4px 8px;margin-right:8px}.eyebrow{font-size:12px;letter-spacing:1.8px;text-transform:uppercase;color:var(--muted);margin-top:38px}h1{font-size:34px;line-height:1.2;letter-spacing:-1px;margin:10px 0 20px}h2{font-size:22px;letter-spacing:-.4px}h3{font-size:16px;margin:0;overflow-wrap:anywhere}
.badge{display:inline-block;border-radius:30px;padding:5px 12px;font-size:12px;font-weight:700;background:#e4eeeb;color:#21594f}.status-findings{background:#fff0d6;color:#875318}.status-error,.status-incomplete{background:#fce5e3;color:#a13d35}
.intro{color:var(--muted);max-width:850px}.banner{border-left:4px solid var(--accent);padding:16px 20px;background:#eaf2ef;margin:24px 0}.banner.status-findings{border-color:#b9812a;background:#fff3df;color:var(--ink)}.banner.status-incomplete,.banner.status-error{border-color:#b14e43;background:#fbecea;color:var(--ink)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:26px 0}.stat{background:white;border:1px solid var(--line);border-radius:10px;padding:20px}.stat span{display:block;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.8px}.stat strong{font-size:32px;letter-spacing:-1px;display:block;margin-top:4px}.stat small{color:var(--muted)}
.meta{display:grid;grid-template-columns:1fr 1fr;gap:8px 24px;margin:20px 0;color:var(--muted);font-size:13px}.meta code{color:var(--ink);overflow-wrap:anywhere}.section-head{display:flex;justify-content:space-between;align-items:center;margin-top:38px;gap:15px}.section-head p{color:var(--muted)}
.filters{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:12px;background:white;border:1px solid var(--line);padding:18px;border-radius:10px;margin:12px 0 20px}label{display:block;font-size:12px;font-weight:650;color:var(--muted)}input,select,button{width:100%;padding:9px 10px;margin-top:6px;border:1px solid #cbd5d6;background:white;border-radius:6px;font:inherit;color:var(--ink)}input:focus,select:focus{outline:2px solid #79b9ae;outline-offset:1px}button{cursor:pointer}.group-mode{max-width:200px}.group{margin:26px 0}.group>h3{font-size:14px;color:var(--muted);margin:0 0 12px;font-weight:650}.finding{background:white;border:1px solid var(--line);border-radius:10px;margin:12px 0;overflow:hidden}.finding-top{display:flex;align-items:center;flex-wrap:wrap;gap:10px;padding:16px 20px;border-bottom:1px solid #edf0f0}.category{font:700 12px ui-monospace,SFMono-Regular,Consolas,monospace;color:#225e55;background:#e8f2ee;padding:4px 8px;border-radius:5px}.source{font-size:12px;color:var(--muted)}.coords{margin-left:auto;font:12px ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--muted)}.finding-body{padding:18px 20px}.file-path{font-size:13px;overflow-wrap:anywhere;margin:0 0 12px;color:var(--muted)}pre,code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}pre{font-size:13px;margin:0;white-space:pre-wrap;overflow-wrap:anywhere;tab-size:4}.value{background:#f3f6f5;border-radius:6px;padding:14px;border:1px solid #e5ebe8}details{margin-top:16px}summary{cursor:pointer;color:var(--muted);font-size:13px;font-weight:600}.context{display:grid;grid-template-columns:auto minmax(0,1fr);gap:16px;background:#f7f9f9;padding:14px;border:1px solid var(--line);border-radius:6px;margin-top:10px}.numbers{color:#8b979d;text-align:right;user-select:none}.empty{padding:42px 20px;text-align:center;border:1px dashed #bacbc7;border-radius:10px;background:white;color:var(--muted)}[hidden]{display:none!important}
.table-wrap{overflow:auto;background:white;border:1px solid var(--line);border-radius:9px;margin-top:14px}table{width:100%;border-collapse:collapse;font-size:13px;text-align:left}th,td{padding:12px 15px;border-bottom:1px solid #e8eded;vertical-align:top}th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.7px;background:#f9fbfa}td:first-child{min-width:200px;max-width:480px;overflow-wrap:anywhere}td code{overflow-wrap:anywhere}.error{border:1px solid #e8c8c3;background:#fff5f3;padding:14px 18px;border-radius:7px;margin:10px 0}.technical{background:white;border:1px solid var(--line);border-radius:8px;padding:16px 20px}.technical pre{margin-top:14px;max-height:400px;overflow:auto}.note{font-size:12px;color:var(--muted)}footer{margin-top:42px;padding-top:20px;border-top:1px solid var(--line);color:var(--muted);font-size:12px;overflow-wrap:anywhere}a{color:var(--accent)}
@media(max-width:800px){main{padding:20px 16px 40px}.stats{grid-template-columns:repeat(2,1fr)}.filters,.meta{grid-template-columns:1fr 1fr}h1{font-size:28px}.coords{margin-left:0}.finding-body,.finding-top{padding:14px}header{align-items:flex-start}.section-head{align-items:flex-start;flex-direction:column}}
@media(max-width:480px){.filters,.meta{grid-template-columns:1fr}.stats{gap:8px}.stat{padding:14px}.stat strong{font-size:26px}}
"""

JS = """
(() => {
  const articles = Array.from(document.querySelectorAll('article.finding'));
  const root = document.getElementById('findings');
  const fields = ['search','category','source','file','group'];
  function update() {
    const search = document.getElementById('search').value.toLocaleLowerCase();
    const category = document.getElementById('category').value;
    const source = document.getElementById('source').value;
    const file = document.getElementById('file').value;
    const byCategory = document.getElementById('group').value === 'category';
    const groups = new Map();
    root.replaceChildren();
    let count = 0;
    for (const article of articles) {
      if ((category && article.dataset.category !== category) ||
          (source && article.dataset.source !== source) ||
          (file && article.dataset.file !== file) ||
          (search && !article.textContent.toLocaleLowerCase().includes(search))) continue;
      const key = byCategory ? article.dataset.category : article.dataset.file;
      let group = groups.get(key);
      if (!group) {
        group = document.createElement('section'); group.className = 'group';
        const heading = document.createElement('h3');
        heading.textContent = byCategory ? article.dataset.category : article.dataset.path;
        group.appendChild(heading); root.appendChild(group); groups.set(key, group);
      }
      group.appendChild(article); count++;
    }
    document.getElementById('visible-count').textContent = 'Показано ' + count + ' из ' + articles.length;
    document.getElementById('no-matches').hidden = count !== 0 || articles.length === 0;
  }
  for (const id of fields) document.getElementById(id).addEventListener('input', update);
  document.getElementById('reset').addEventListener('click', () => {
    for (const id of fields) document.getElementById(id).value = id === 'group' ? 'file' : '';
    update();
  });
  update();
})();
"""


def visible(value, *, inline=False):
    result = []
    for c in str(value):
        if inline and c in "\r\n\t":
            result.append({"\r": "\\r", "\n": "\\n", "\t": "\\t"}[c])
        elif (
            (ord(c) < 32 and c not in "\r\n\t")
            or 127 <= ord(c) < 160
            or unicodedata.category(c) == "Cf"
        ):
            result.append(f"\\u{ord(c):04x}")
        else:
            result.append(c)
    return "".join(result)


def esc(value, *, inline=False):
    return html.escape(visible(value, inline=inline), quote=True).replace("\r", "&#13;")


def _hash(value):
    return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode("ascii")


def render_html(report):
    validate_report(report)
    result, scan, counts = (
        report["result"],
        report["scan"],
        report["coverage"]["counts"],
    )
    status = result["status"]
    title = {
        "clean": "Находок нет",
        "findings": "Обнаружены чувствительные данные",
        "incomplete": "Проверка не завершена",
        "error": "Проверка завершилась ошибкой",
    }[status]
    assurance = {
        "snapshot_verified": "Проверена поддерживаемая текстовая область снимка.",
        "baseline_verified": "Проверены изменения; неизменённые файлы подтверждены доверенным baseline.",
        "changed_files_only": "Проверены только выбранные изменённые файлы. Неизменённые файлы не подтверждены.",
        "none": "Полнота проверки не подтверждена. Ошибки имеют приоритет над отсутствием находок.",
    }[result["assurance"]]
    csp = f"default-src 'none'; script-src 'sha256-{_hash(JS)}'; style-src 'sha256-{_hash(CSS)}'; base-uri 'none'; form-action 'none'; connect-src 'none'; object-src 'none'"
    parts = [
        f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="{html.escape(csp,quote=True)}"><title>ru-llm-scanner · {title}</title><style>{CSS}</style></head><body><main>',
        f'<header><div class="brand"><b>ru</b>llm-scanner</div><span class="badge status-{status}">{esc(status.upper())} · EXIT {result["exit_code"]}</span></header>',
        f'<div class="eyebrow">Локальный аудит · {esc(scan["mode"])}</div><h1>Проверка репозитория</h1><p class="intro">Содержимое Git-состояния · {esc(report["created_at"])}</p>',
        f'<div class="banner status-{status}"><strong>{title}</strong><br>{assurance}</div><div class="stats">',
    ]
    for label, number, note in [
        ("Находки", result["findings_count"], "все места сохранены"),
        ("Проанализировано", counts["analyzed"], f'из {counts["target"]} записей B'),
        (
            "Наследовано",
            counts["inherited"],
            f'не подтверждено: {counts["unverified"]}',
        ),
        (
            "Ошибки",
            len(report["errors"]),
            f'исключено / не поддерживается: {counts["excluded"]} / {counts["unsupported"]}',
        ),
    ]:
        parts.append(
            f'<div class="stat"><span>{label}</span><strong>{number}</strong><small>{note}</small></div>'
        )
    parts.append('</div><div class="meta">')
    for label, value in [
        ("Коммит B", scan["target_commit"]),
        ("Коммит A", scan["base_commit"]),
        ("Assurance", result["assurance"]),
        ("Baseline", report["baseline"]["status"]),
    ]:
        parts.append(
            f'<div>{label}<br><code>{esc(value if value is not None else "—")}</code></div>'
        )
    parts.append(
        '</div><p class="note">Отчёт содержит полные чувствительные значения. Не публикуйте его. Отсутствие находок не гарантирует полноту распознавания; история, исключения и неподдерживаемые объекты не подтверждаются.</p>'
    )
    if report["errors"]:
        parts.append('<section aria-label="Ошибки"><h2>Ошибки проверки</h2>')
        for error in report["errors"]:
            parts.append(
                f'<div class="error"><strong>{esc(error["code"])}</strong> · {esc(error["stage"])}<br><code>{esc(error["file_id"] or "Ошибка запуска")}</code></div>'
            )
        parts.append("</section>")
    parts.append(
        '<section aria-label="Находки"><div class="section-head"><h2>Находки</h2><p id="visible-count" role="status" aria-live="polite"></p></div><div class="filters"><label>Поиск по находкам<input id="search" type="search" placeholder="Файл, категория, значение…"></label>'
    )
    for field, label, items in [
        (
            "category",
            "Категория",
            [(v, v) for v in sorted({f["category"] for f in report["findings"]})],
        ),
        (
            "source",
            "Источник",
            [(v, v) for v in sorted({f["source"] for f in report["findings"]})],
        ),
        (
            "file",
            "Файл",
            [
                (f["id"], f'{f["path"]} · {f["id"][:8]}')
                for f in report["files"]
                if f["status"] == "analyzed"
            ],
        ),
    ]:
        parts.append(
            f'<label>{label}<select id="{field}"><option value="">Все</option>'
        )
        parts.extend(
            f'<option value="{esc(key,inline=True)}">{esc(label,inline=True)}</option>'
            for key, label in items
        )
        parts.append("</select></label>")
    parts.append(
        '<label>Группировка<select id="group"><option value="file">По файлам</option><option value="category">По категориям</option></select></label><div><button type="button" id="reset">Сбросить фильтры</button></div></div><div id="findings">'
    )
    for f in report["findings"]:
        context = f["context"]
        numbers = "\n".join(
            str(n) for n in range(context["start_line"], context["end_line"] + 1)
        )
        path_label = f'{f["path"]} · {f["file_id"][:8]}'
        parts.append(
            f'<article class="finding" data-category="{esc(f["category"],inline=True)}" data-source="{esc(f["source"],inline=True)}" data-file="{f["file_id"]}" data-path="{esc(path_label,inline=True)}"><div class="finding-top"><span class="category">{esc(f["category"])}</span><span class="source">{esc(f["source"])} · score {f["score"]:.3f}</span><span class="coords">{f["start_line"]}:{f["start_column"]} → {f["end_line"]}:{f["end_column"]}</span></div><div class="finding-body"><p class="file-path">{esc(path_label,inline=True)}</p><pre class="value">{esc(f["value"])}</pre><details open><summary>Контекст · строки {context["start_line"]}–{context["end_line"]}</summary><div class="context"><pre class="numbers" aria-hidden="true">{numbers}</pre><pre>{esc(context["text"])}</pre></div></details><p class="note">Rule: {esc(f["rule_id"] or "—")} · <code>{f["id"]}</code></p></div></article>'
        )
    parts.append(
        '</div><div class="empty" id="no-matches" hidden>Нет находок по выбранным фильтрам.</div>'
    )
    if not report["findings"]:
        parts.append(
            f'<div class="empty">{"Находок в проверенной области нет." if result["exit_code"]==0 else "Находки не получены. Учитывайте статус и ошибки проверки."}</div>'
        )
    parts.append(
        '</section><section id="coverage"><div class="section-head"><h2>Охват файлов</h2></div><p class="note">Все записи B, включая неподтверждённые и исключения. Управляющие/невидимые символы показаны как \\uXXXX; исходные значения сохранены в JSON.</p><div class="table-wrap"><table><thead><tr><th>Файл</th><th>Изменение</th><th>Статус</th><th>Причина</th><th>Размер / кодировка</th></tr></thead><tbody>'
    )
    for f in report["files"]:
        parts.append(
            f'<tr><td>{esc(f["path"],inline=True)}<details><summary>Raw path / ID</summary><code>{f["path_bytes_b64"]}<br>{f["id"]}</code></details></td><td>{esc(f["change"])}</td><td>{esc(f["status"])}</td><td>{esc(f["reason"] or "—")}</td><td>{f["size_bytes"] if f["size_bytes"] is not None else "—"} / {esc(f["encoding"] or "—")}</td></tr>'
        )
    parts.append("</tbody></table></div></section>")
    if report["deleted_files"]:
        parts.append(
            '<section><h2>Удалённые записи A</h2><div class="table-wrap"><table><thead><tr><th>Путь</th><th>Mode / OID</th></tr></thead><tbody>'
        )
        for f in report["deleted_files"]:
            parts.append(
                f'<tr><td>{esc(f["path"],inline=True)}<br><code>{f["path_bytes_b64"]}</code></td><td><code>{f["mode"]}<br>{f["object_oid"]}</code></td></tr>'
            )
        parts.append("</tbody></table></div></section>")
    technical = {
        key: report[key]
        for key in ("scan", "configuration", "engine", "baseline", "coverage")
    }
    parts.append(
        f'<details class="technical"><summary>Профиль, происхождение и параметры</summary><pre>{esc(json.dumps(technical,ensure_ascii=False,indent=2))}</pre></details><footer>ru-llm-scanner {esc(report["scanner"]["version"])} · {report["report_id"]}<br>Полные значения и контрольные данные — в report.json. Состояние доставки артефактов подтверждается кодом завершения команды.</footer></main><script>{JS}</script></body></html>'
    )
    return "".join(parts)
