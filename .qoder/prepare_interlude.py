"""一次性只准备已批准的间隙章生产清单；排他创建，绝不执行生产节点。"""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'shared'))
import production
import yaml

project = Path('D:/桃园密码')
manifest = project / 'interlude-production.yaml'
if manifest.exists():
    raise SystemExit('清单已存在；拒绝覆盖。')

sources = ['间隙章大纲.md', 'handoff.md', '人物小传.md', '设定/事实账本/snapshot.json',
           'assets/voice_sample.md', '正文/050-第50章-归朝堂.md']
for source in sources:
    if not (project / source).is_file():
        raise SystemExit(f'输入不存在：{source}')

# 对旧稿、旧图、账本、旧运行记录建立验证基线，不改任何一份旧文件。
old_files = [project / p for p in ('graph.yaml', 'volume_graph.yaml', 'pipeline.json',
                                  'volume_pipeline.json', *sources)]
old_files += list((project / '正文').glob('*.md'))
old_files += [p for p in (project / '工作区').rglob('*') if p.is_file()]
baseline = {p.relative_to(project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in old_files if p.is_file()}
with (ROOT / '.qoder/interlude-baseline.json').open('x', encoding='utf-8') as handle:
    json.dump(baseline, handle, ensure_ascii=False, indent=2)

common = '''本轮是第51—54章从零重写，不复用旧51—54章正文作为本轮产物；大纲末尾“五步流程/第51章微调”是旧执行方案，不具有流程控制权。唯一执行链是当前冻结的十节点模板。
按《间隙章大纲.md》本章细纲取舍材料。只使用本轮前一章已正式放行的稿件承接，不读取第55章及以后正文、不倒灌后续副本情报；handoff及人物档案包含作者视角秘密时只用于划定盲区，不写入顾君知情。
受限第三人称固定在顾君可感知范围；白艺内心通过对白、动作与顾君的有限理解表达，不能直接跳进她的脑内。现代通俗白话90%—95%，历史语汇只作必要点缀；心理推演和身体反应有情境依据，禁止机械堆砌。正文目标2000—2500字，对白约25%—40%，长短句因情节自然交替，不全篇切成短碎句。
张洋称顾君只用老顾/顾子/君儿，战友称谓自然；对创伤中的朋友温和克制，不怒喝闭嘴/给我闭嘴/别废话。禁用“一死生”“齐彭殇”“虚诞”“妄作”。写即时创伤表现，不凭当天症状在叙述中擅自作长期PTSD诊断。
秦华的暗桩身份、卢夏的敌方身份均是作者层秘密；没有剧情证据不得让主角识破。历史档案中的超自然设定与真实史料分层，物理仪器读数、人物假说、已证实结论分开，不能把磁强计/红外仪能直接测时空曲率或绝对负温写成已证科学能力。
只写当前节点指定产物，不覆盖旧正文、不改清单结构、不跳过检测或作者审批；正式归档路径保留原文件名，章节正文标题采用新细纲标题。'''

beats = {
    51: '第一天09:15—17:30。窒息呛醒、手腕淤伤、古墨残片与七个半小时时差；论坛加密私信秦华【关山难越】，确认六人脱困、老莫和苏晚晴静养；探望张洋，发小默契安抚，确立后方休养和论坛监控；傍晚白艺端雪梨银耳汤相迎。古墨松烟香带来的头痛缓解只写主观体验。严禁提前解释玉玺七锚点、雷台、居延和第三副本。',
    52: '第一天17:40—19:30。承接第51章雪梨汤；白艺为顾君换药，保持伤情谨慎，不把包扎写成复位治疗；两人浅复盘王羲之传序、五石散、刘弼、未现玉玺与秦华应激。对秦华只有有边界的疑问，不确定其恶意，更不得从表情诊断杏仁核。遭遇历史解释瓶颈，顾君提议问老莫，白艺主动同行，夜色中并肩而行。七锚点和雷台内参留到第53章。',
    53: '第一天20:00—22:30。老莫书斋四人汇合；由老莫有来源地讲述大醮与玉玺七锚点家族说法；苏晚晴展示雷台档案，引出铜车马、官印及现代金属/磁化异常。林栩【大汉铁骑】的居延帖与匿名权威【成吉思汗的小马驹】的考据指引把注意力导向河西。卢夏全程看似可靠，不挑衅、不跳反；主角不知道其身份及日后48克钛合金军牌因果。未核实历史数字/身份须在上下文标明来源层级或待核实，不能把剧情私密档案当真实史实背书。',
    54: '第一天23:00—第二天00:15。回顾君出租屋测试，老莫苏晚晴可远程见证；白艺带三轴磁强计、测距仪和红外仪，记录可观测量并说明未知。古墨与居延数据同时呈现后发生异常，先写读数/仪器失效/茶水变化，再写假说，不把时间先后直接当证实的物理机制。铜角、风沙与现实空间异变推进，两人共同面对未知，在即将进入河西绝域前截断；仪器随白艺进入下一阶段，不写第55章落地剧情。',
}
outputs = {51: '051-间隙章一-回响.md', 52: '052-间隙章二-复盘.md',
           53: '053-间隙章三-暗流.md', 54: '054-间隙章四-引信.md'}
titles = {51: '回响', 52: '同行', 53: '问道', 54: '引信'}
chapters = []
for number, title in titles.items():
    context_sources = sources[:4] + ([sources[-1]] if number == 51 else [])
    overrides = {}
    for node in ('explore_context', 'scene_beats', 'draft_chapter', 'deai_polish', 'audit_persona', 'review_qc'):
        overrides[node] = {'prompt_append': common + '\n本章任务：' + beats[number]}
    overrides['explore_context']['inputs_add'] = context_sources
    overrides['explore_context']['prompt_append'] += '\n输出已确证/合理推测/绝对未知三栏表、称谓白名单和输入矛盾清单。只对齐事实，不替后续节点编剧情。'
    for node in ('scene_beats', 'draft_chapter', 'audit_persona', 'review_qc'):
        overrides[node]['inputs_add'] = ['间隙章大纲.md', '人物小传.md']
    chapters.append({'id': f'ch{number:03d}', 'params': {
        'chapter_num': number, 'chapter_title': title, 'volume_name': '现实间隙卷_兰亭余波',
        'genre': '历史悬疑 × 规则怪谈 × 魏晋智斗', 'tone': '考据冷硬、现实余震、克制温情与深度心理推演',
        'target_words': 2300, 'voice_sample': 'assets/voice_sample.md',
        'chapter_output': '正文/' + outputs[number],
    }, 'overrides': overrides})

doc = production.create_document('桃园密码 · 现实间隙卷51—54章 · 从零重写', chapters, host='qoder')
production.validate_document(doc, project)
with manifest.open('x', encoding='utf-8') as handle:
    yaml.safe_dump(doc, handle, allow_unicode=True, sort_keys=False)
for rel, fingerprint in baseline.items():
    assert hashlib.sha256((project / rel).read_bytes()).hexdigest() == fingerprint, rel
print(json.dumps({'manifest': str(manifest), 'task_id': doc['id'], 'template': doc['template']['hash'],
                  'nodes_per_chapter': 10, 'chapters': list(titles), 'old_files_unchanged': len(baseline),
                  'state_written': (project / '工作区/生产任务' / doc['id'] / 'state.json').exists()}, ensure_ascii=False))
