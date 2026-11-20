"""Original Hero callbacks and the route state at each native input boundary."""
import re

if __package__:
    from .scenes import _battle_action, _ending_art, _select_art, _setup
else:
    from scenes import _battle_action, _ending_art, _select_art, _setup


def _require(source, *commands):
    missing = [cmd for cmd in commands if cmd not in source.text]
    if missing:
        raise ValueError(f'勇者路线的原作触发条件已变化：{missing[0]}')


def _preset(flow, gallery, source, label, title, flags, floor, section, *, boundaries=(), battle_exit=None):
    route = flow.trace(source, label, dict(flags, partnerCharacter='hero'), boundaries, battle_exit=battle_exit)
    if route['issues']:
        raise ValueError(f"勇者剧情 {source}.{label} 无法验证：{route['issues']}")
    exits = [stop for stop in route['exits'] if stop != '@title']
    return dict(title=title, setupCommands=_setup('Hero', floor, section, flags, label),
                exits=exits, naturalTitle='@title' in route['exits'], naturalReturn=route['returns'],
                choices=route['choices'], galleryIds=_select_art(route['visited'], gallery) +
                _ending_art(source, label, flags, route, gallery),
                issues=[], status='script-reviewed')


def _scene(flow, source, label, chapter, title, presets, evidence):
    exits = sorted({item for p in presets for item in p['exits']})
    returns = any(p['naturalReturn'] for p in presets)
    return dict(id=f'{source}.{label}', source=source, label=label, line=flow.sources[source].labels[label],
                group='Hero', chapter=chapter, title=title, setupCommands=presets[0]['setupCommands'],
                exits=exits, boundary='return' if returns and not exits else 'label', naturalReturn=returns,
                naturalTitle=any(p['naturalTitle'] for p in presets), presets=presets,
                galleryIds=list(dict.fromkeys(item for p in presets for item in p['galleryIds'])),
                status='script-reviewed', evidence=evidence)


def _arrow(flow, gallery):
    hero = flow.sources['Scenario_Hero1']
    dungeon = flow.sources['Dungeon']
    # Validate this one dedicated roulette subroutine, including its *return* to
    # the outer dialogue. The header's non-interactive choice never owns a branch.
    def transfers(source, start, end):
        return [command for command in source.text[source.labels[start]:source.labels[end]] if
                re.match(r'^@(gosub|goto|choiceR?|stop|return|input|quickLoad|title)\b', command, re.I)]

    path = transfers(hero, 'Outcast1', 'Outcast2')
    roulette = transfers(dungeon, 'eventHero1', 'ResetAfterEvent')
    header = transfers(dungeon, 'beforeEventChoice', 'beforeRoulette')
    if (path != ['@gosub Dungeon.eventHero1', '@return'] or len(header) != 3 or
            'button:Buttons/CustomChoiceHandlerButton_LikeTitleButtonCantTouch' not in header[0] or
            'goto:' in header[0] or header[1:] != ['@gosub .ResetRouletteState', '@return'] or
            transfers(dungeon, 'ResetRouletteState', 'beforeEventChoice') != ['@return'] or
            len(roulette) != 4 or roulette[0] != '@gosub .beforeEventChoice' or
            not roulette[1].startswith('@choice ') or not roulette[1].endswith('handler:Roulette goto:.eventHero1_avoid') or
            roulette[2:] != ['@stop', '@return']):
        raise ValueError('勇者挡箭事件的原作躲避选项或返回路径已变化')
    reach = {'Scenario_Hero1': range(hero.labels['Outcast1'], hero.labels['Outcast2']),
             'Dungeon': range(dungeon.labels['eventHero1'], dungeon.labels['ResetAfterEvent'])}
    preset = dict(title='原作入口', setupCommands=_setup('Hero', 1, 2, {}, 'Outcast1'), exits=[],
                  naturalTitle=False, naturalReturn=True, choices=1, galleryIds=_select_art(reach, gallery),
                  status='script-reviewed', issues=[])
    return _scene(flow, 'Scenario_Hero1', 'Outcast1', 1, '勇者挡下陷阱箭', [preset],
                  '原作第一层专属陷阱只有一个躲避选项，接回勇者中箭、疗伤与道谢后返回。')


def _final_argument(flow, gallery):
    dungeon = flow.sources['Dungeon']
    _require(dungeon, '@gosub Scenario_Hero5.PriestBattleBefore')
    source = 'Scenario_Hero5'
    label = 'PriestBattleBefore'
    _require(flow.sources[source], '@set battleTarget="priest"', '@set addEnemyResourceNames="priest"')
    _require(flow.sources['Battle'], '@gosub .PriestFinalEnsureHeroSpecialWeapons if:xPriestFinalRoute=="hero"',
             '@gosub .PriestFinalFormStart if:battleTarget=="priest"', '# InitializeCommand')
    flags = {'eventNum': 505, 'xSwitchScenario5MapStop': 1, 'xSwitchCanSelectAnyItemByTurn': 0}
    preset = _preset(flow, gallery, source, label, '原作入口', flags, 5, 5, battle_exit='Battle.InitializeCommand')
    if preset['choices'] != 2 or preset['exits'] != ['Battle.InitializeCommand']:
        raise ValueError('僧侣决战前的两种回答或首回合边界已变化')
    return _scene(flow, source, label, 5, '决战前 · 僧侣的提议', [preset],
                  '第五层事件 505。保留两种回应、汇合后的回忆和战斗出场，到第一手指令返回。')


def _final_blow(flow, gallery, fourth_phase):
    source = 'Scenario_Hero5'
    label = 'PriestBattleAfter'
    native = flow.sources[source]
    _require(native, '@if tempHeroRoute5StealHit', '@goto .HeroRoute5_Hit', '@goto .HeroRoute5_Miss',
             '@goto .HeroRoute5_End', '@set endingType="hero"', '@set xSwitchPriestFinalHeroRetryBattle=1',
             '@goto GameOver')
    _require(flow.sources['GameOver'], '# AfterOptionalGameOverVisual', '@gosub .GameOverBeforeCore',
             '# GameOverBeforeCore', '# Choice', '@goto .PriestFinalHeroRetryBattle if:xSwitchPriestFinalHeroRetryBattle==1')
    win = _preset(flow, gallery, source, label, '夺取成功', {'tempHeroRoute5StealHit': 1}, 5, 5)
    lose = _preset(flow, gallery, source, label, '夺取失败', {'tempHeroRoute5StealHit': 0}, 5, 5,
                   boundaries=('GameOver',))
    if not win['naturalTitle'] or lose['exits'] != ['GameOver']:
        raise ValueError('勇者终战分歧后的原作转场已变化')
    # After the complete authored loss, allow the native defeat screen (including
    # its random artwork). Intercept before GameOver prepares reinforcements or retry.
    screen = flow.sources['GameOver']
    start = screen.labels['gameover']
    stop = screen.text.index('@gosub .GameOverBeforeCore', screen.labels['AfterOptionalGameOverVisual'])
    if not start < screen.labels['AfterOptionalGameOverVisual'] < stop < screen.labels['Choice']:
        raise ValueError('勇者败北画面与重试菜单的顺序已变化')
    lose['exits'] = ['GameOver.GameOverBeforeCore']
    lose['galleryIds'].extend(_select_art({'GameOver': range(start, stop)}, gallery))
    _require(flow.sources['Battle'], '@gosub .HeroLinkLightningAnimationStart', '@goto .PriestFinalHeroFinisherHitAttack',
             '@goto .PriestFinalHeroFinisherMiss', '@goto .PriestFinalHeroFinisherBattleEnd',
             '@set tempHeroRoute5StealHit=GetSectionDataLength()>0&&GetSectionOptionValueAtPosByType(0,"StealWeapon")>0',
             '@gosub StatusFunc.GainExp if:battleTarget!="priest"||xPriestFinalRoute!="hero"||xSwitchPriestFinalHeroFinalBreakDone!=1')
    _require(native, '@gosub Battle', '@gosub Dungeon.BeforeNovelHideUIWithoutMenu')
    both = dict(win, title='亲自操作夺取判定', exits=lose['exits'],
                galleryIds=list(dict.fromkeys(win['galleryIds'] + lose['galleryIds'])))
    presets = []
    for mode, variant in enumerate((win, lose, both), 1):
        action = fourth_phase['actionAtFirstCommand']
        action = dict(action, commands=[f'@set v15HeroFinisherMode={mode}'] + action['commands'])
        presets.append(dict(variant, setupCommands=fourth_phase['setupCommands'],
                            actionAtFirstCommand=action, exits=['Battle.InitializeCommand'] + variant['exits'],
                            finishCommands=['@gosub Dungeon.BeforeNovelHideUIWithoutMenu',
                                            '@goto Scenario_Hero5.PriestBattleAfter']))
    scene = _scene(flow, 'Battle', 'Start', 6, '最后的一击', presets,
                   '第四形态濒死触发累积的诅咒，原作联手出牌、命中雷击或落空接回告别与结局；可按预设或亲自判定。')
    return dict(scene, id=f'{source}.{label}', actionAtFirstCommand=presets[0]['actionAtFirstCommand'],
                evidenceRows=fourth_phase['evidenceRows'])


def _elite_aftermaths(flow, gallery):
    source, label = 'Scenario_Hero3', 'Dropout3_EliteAfter'
    _require(flow.sources[source], '@gosub Scenario.SeaDragonBattleCore',
             '@goto .HeroBookSympathyEnd if:xSwitchOutcastChoiceCantTrustHero==1&&xSwitchChoiceVillainessLastKaibutsu==1')
    presets = [_preset(flow, gallery, source, label, title,
                       {'xSwitchOutcastChoiceCantTrustHero': value, 'xSwitchChoiceVillainessLastKaibutsu': value}, 3, 3)
               for title, value in [('理解勇者的心情', 0), ('仍对勇者心存疑虑', 1)]]
    yield _scene(flow, source, label, 3, '海龙战后 · 寻回的书', presets,
                 '海龙精英战后的原作连续回调，两种过去选择保留主人公是否理解勇者的差异。')
    source, label = 'Scenario_Hero4', 'Slime3_EliteAfter'
    _require(flow.sources[source], '@gosub Scenario.GiantBattleCore', '@return if:xSwitchHeroDropoutChoiceNotBelieve==1')
    preset = _preset(flow, gallery, source, label, '相信勇者', {'xSwitchHeroDropoutChoiceNotBelieve': 0}, 4, 3)
    yield _scene(flow, source, label, 4, '巨人战后 · 两人的约定', [preset],
                 '原作巨人战后，相信勇者的路线继续至两人约定，另一条路线立即返回。')


def _final_phases(flow, gallery):
    # The ordinary attack targets the priest even when her summoned limbs remain.
    # The native HP transition has no limb-count requirement.
    forms = [(1, '第一形态 · 踏出一步', 'doll', '人偶'),
             (2, '第二形态 · 同行的冒险', 'destructionMagicSword', '魔剑'),
             (3, '第三形态 · 不愿放弃的光', 'magiaTakt', '魔杖'),
             (4, '第四形态 · 命运的分界线', None, None)]
    for phase, title, relic, relic_title in forms:
        setup = _setup('Hero', 5, 5, {}, 'PriestBattleAfter') + [
            '@gosub Func.ShowSettings', '@set battleTarget="priest"', '@set xSwitchBoss5BattleEvent=1',
            '@set xSwitchRunAllowed=0', '@set xSwitchCanSelectAnyItemByTurn=0',
            f'@set xSwitchSystemDebugPriestPhase={phase}', '@set addEnemyResourceNames="priest"', '@set showEnemyUI=false']
        commands = ['@set enemy{xPriestFinalSlot}Health=1', '@set enemy{xPriestFinalSlot}StateBlock=0',
                    '@set enemy{xPriestFinalSlot}StateBarrier=0', '@set enemy{xPriestFinalSlot}StateEvading=0',
                    '@set selectCommand=-1', '@set selectionEnemyTargetId=GetEnemyStr(xPriestFinalSlot)']
        proof = [('Battle', cmd) for cmd in ['@set xPriestFinalRoute="hero"',
                 '@set xPriestFinalPhase=xSwitchSystemDebugPriestPhase', '@set xPriestFinalSlot=tempBattleStartEnemyCount',
                 '@gosub .PriestFinalFormStart if:battleTarget=="priest"', '# PlayerAttack',
                 '@set z=PrepareSelectedTargetHits(selectCommand,selectionEnemyTargetId)']]
        if phase <= 3:
            proof.extend(('Battle', cmd) for cmd in [
                f'@gosub .PriestFinalHeroForm{phase}StartText', '@gosub .PriestFinalPhaseTransitionCheck',
                '@return if:enemy{xPriestFinalSlot}Health>0&&enemy{xPriestFinalSlot}Death!=1',
                '@gosub .PriestFinalPhaseClearText', f'@gosub .PriestFinalHeroForm{phase}CounterText',
                f'@if HasBattleUsedOrBrokenItem("{relic}")', f'@gosub Func.AddItem if:!HasItem("{relic}")',
                '@set z=RecordBattleUsedItem(selectCommand) if:selectCommand>0',
                '@set xPriestFinalPhase=priestFinalNextPhase'])
            proof.append(('Func', '@addItem "{addItem}" AddedIndexSaveValue:"itemAddedIndex"'))
            note = '从原作形态登场开始；锁定僧侣，提交普通攻击，进入原作反击对话与下一形态。'
        else:
            proof.extend(('Battle', cmd) for cmd in [
                '@if battleTarget=="priest"&&xPriestFinalRoute=="hero"&&xPriestFinalPhase>=4&&tempEnemyDeathCheckId==xPriestFinalSlot&&tempEnemyResourceName=="priestHeroRouteForm4"&&xSwitchPriestFinalHeroFinalBreakDone!=1',
                '@set enemyStealItem="tumikasaCurse"', '@gosub Dungeon.GetItemMessage',
                '@gosub .PriestFinalHeroAcquireTumikasaCurse', '@set xSwitchPriestFinalHeroFinalBreakDone=1',
                '@set heroLinkLightningPhase=30',
                '@gosub .PriestFinalHeroFinisherIntro if:battleTarget=="priest"&&xPriestFinalRoute=="hero"&&xSwitchPriestFinalHeroFinalBreakDone==1&&heroLinkLightningPhase==30',
                '@set heroLinkLightningPhase=31', '@goto .PriestFinalHeroLinkLightningChoice'])
            note = '以普通攻击触发第四形态濒死时的原作诅咒获取、僧侣蓄力与决战序幕，到联手出牌前返回。'
        scene = _battle_action(flow, gallery, f'Battle.Action.HeroPriestPhase{phase}', 'Hero', 5,
                               title, setup, commands, (), proof, note)
        scene['actionAtFirstCommand']['selectBoss'] = True
        if relic:
            # First gives an iron sword and potion. Register this relic first so the
            # stock boss setup sees it in inventory and supplies just the other two.
            preset = scene['presets'][0]
            preset['title'] = f'未使用{relic_title}'
            used_setup = setup + [f'@set addItem="{relic}"', '@gosub Func.AddItem',
                                  '@set v15HeroRelicSlot=itemAddedIndex']
            used_action = dict(scene['actionAtFirstCommand'],
                               commands=['@set z=RecordBattleUsedItem(v15HeroRelicSlot)'] + commands)
            scene['presets'].append(dict(preset, title=f'已使用{relic_title}', setupCommands=used_setup,
                                         actionAtFirstCommand=used_action))
        yield scene


def _final_defeat(flow):
    battle = flow.sources['Battle']
    gameover = flow.sources['GameOver']
    _require(battle, '@set xPriestFinalLoopCount=enemy{xPriestFinalSlot}StateSelfContradiction',
             '@gosub .PriestFinalPlayerDeathTextCheck if:battleTarget=="priest"&&xPriestFinalSlot>0&&xSwitchPriestFinalCurseShortageGameOver!=1',
             '@if xPriestFinalLoopCount<=1', '@elseif xPriestFinalLoopCount==2', '@elseif xPriestFinalLoopCount==3',
             *[f'@set xPriestFinalHeroDeathGameOverTextType={n}' for n in range(1, 5)])
    _require(gameover, '@gosub .PriestFinalHeroDeathFirstGameOverEvent if:xSwitchPriestFinalHeroDeathFirstGameOver==1',
             '@set xSwitchPriestFinalSkipGameOverVisual=1',
             '@goto .AfterOptionalGameOverVisual if:xSwitchPriestFinalSkipGameOverVisual==1',
             '@choice "{tempNeverGiveUpChoiceMessage}" goto:.PriestFinalHeroDeathFirstGameOverChoiceEnd',
             '@gosub .GameOverBeforeCore')
    presets = []
    endings = [('第一次', 'First', '<=1'), ('第二次', 'Second', '==2'),
               ('第三次', 'Loop', '==3'), ('第四次起', 'Fourth', '>=4')]
    for count, (title, variant, condition) in enumerate(endings, 1):
        _require(gameover, f'@gosub Battle.PriestFinalHeroDeath{variant}Text if:xPriestFinalHeroDeathGameOverTextType{condition}')
        _require(battle, f'# PriestFinalHeroDeath{variant}Text')
        flags = {'battleTarget': '"priest"', 'xPriestFinalRoute': '"hero"', 'xPriestFinalLoopCount': count,
                 'xSwitchPriestFinalPlayerDeathTextDone': 0}
        setup = _setup('Hero', 5, 5, flags, 'PriestBattleAfter') + ['@gosub Battle.PriestFinalPlayerDeathTextCheck']
        presets.append(dict(title=title, setupCommands=setup, exits=['GameOver.GameOverBeforeCore'],
                            naturalTitle=False, naturalReturn=False, choices=1, galleryIds=[], issues=[], status='script-reviewed'))
    scene = _scene(flow, 'GameOver', 'gameover', 5, '决战败北 · 决不放弃', presets,
                   '原作根据勇者最终战败北周次选择僧侣台词；保留不放弃的选项，在重试前结束。')
    return dict(scene, id='GameOver.HeroFinalNeverGiveUp')


def integrate(catalog_scenes, flow, gallery_rows):
    """Replace verified Hero candidates in place; insert recovered aftermaths in story order."""
    phases = list(_final_phases(flow, gallery_rows))
    finale = _final_blow(flow, gallery_rows, phases.pop())
    updates = [_arrow(flow, gallery_rows), _final_argument(flow, gallery_rows), finale]
    updates.extend(_elite_aftermaths(flow, gallery_rows))
    updates.extend(phases)
    updates.append(_final_defeat(flow))
    insertion_points = {'Scenario_Hero3.Dropout3_EliteAfter': 'Scenario_Hero3.DropoutBattleBefore',
                        'Scenario_Hero4.Slime3_EliteAfter': 'Scenario_Hero4.SlimeBattleBefore'}
    for scene in updates:
        ids = [entry['id'] for entry in catalog_scenes]
        if scene['id'] in ids:
            catalog_scenes[ids.index(scene['id'])] = scene
        else:
            target = insertion_points.get(scene['id'], 'Scenario_Hero5.PriestBattleAfter')
            catalog_scenes.insert(ids.index(target), scene)


def patch_program(edits, scripts):
    """Keep the two authored joint cards, carry the selected gauge result into stock Battle."""
    # Use the generated trigger numbers. A suspended choice from another replay
    # can never reuse the finisher override, even if its local mode value persists.
    trigger = None
    flags = {}
    for _, command in sorted(edits['Test2'].items()):
        if not isinstance(command, str):
            continue
        if command.startswith('# '):
            match = re.fullmatch(r'# Trigger(\d+)', command)
            trigger = match.group(1) if match else None
        if trigger and command.startswith('@set v15HeroFinisherMode='):
            flags[int(command.rsplit('=', 1)[1])] = trigger
    if not flags:
        return
    if flags.keys() != {1, 2, 3}:
        raise ValueError('无法识别勇者联手雷击的三个原作结果预设')
    scope = '(' + '||'.join(f'v15Scene=={flags[n]}' for n in (1, 2, 3)) + ')&&v15ActionIssued==1'
    original = scripts['Battle']
    lines = [r[3].strip() for r in original]
    changes = edits['Battle']
    if '# V15HeroCardStop' in changes.values():
        return
    def location(start, end, text):
        indices = [i for i in range(start, end) if lines[i] == text]
        if len(indices) != 1:
            raise ValueError(f'原作勇者联手指令已变化：{text}')
        return indices[0]

    hand = location(lines.index('# NextAction'), lines.index('# InitializeCommand'), '@prewarmBattleHand')
    if original[hand-1][1] not in ('Empty', 'Comment'):
        raise ValueError('勇者联手指令的出牌准备边界已变化')
    cards = lines.index('# PriestFinalHeroLinkLightningChoice')
    stop = location(cards, lines.index('# PriestFinalHeroLinkLightningCardSelected'), '@stop')
    if not lines[stop-1].startswith('@transferCurseToBattleCard ') or not lines[stop-2].startswith('@transferCurseToBattleCard '):
        raise ValueError('勇者联手卡的原生充能演出已变化')
    gauge = lines.index('# PriestFinalHeroFinisherGauge')
    end = lines.index('# RefreshBattleOrderChangeable')
    bar = location(gauge, end, '@summonAttackBar itemResourceName:"kick" exEffects:"oppositeSideCursor=1" stopPositionsVarName:"stopPositions"')
    result = location(bar, end, '@set tempHeroRoute5StealHit=GetSectionDataLength()>0&&GetSectionOptionValueAtPosByType(0,"StealWeapon")>0')
    insert = {hand-1: '@goto .V15HeroJointHand if:' + scope + '&&(heroLinkLightningPhase==31||heroLinkLightningPhase==32)',
              stop: '@goto .V15HeroCardStop', bar: '@gosub .V15HeroGaugeInput',
              result: '@gosub .V15HeroGaugeResult'}
    if changes.keys() & insert.keys():
        raise ValueError('勇者终战守卫与其他回放补丁重叠')
    cursor = max(len(lines), max(changes, default=-1) + 1)
    native_return = ('Battle', lines.index('@return'))
    extra = ['# V15HeroJointHand', ('Battle', hand), '@goto .PriestFinalHeroLinkLightningChoice',
             '# V15HeroCardStop', '@goto .V15HeroPlayCard if:' + scope, ('Battle', stop),
             '# V15HeroPlayCard', '@wait 0.6', '@set selectCommand=-203', '@goto .PlayerAttack',
             '# V15HeroGaugeInput', '@goto .V15HeroGaugeReturn if:' + scope + '&&v15HeroFinisherMode<=2',
             ('Battle', bar), '# V15HeroGaugeReturn', native_return,
             '# V15HeroGaugeResult', ('Battle', result), '@set tempHeroRoute5StealHit=true if:' + scope + '&&v15HeroFinisherMode==1',
             '@set tempHeroRoute5StealHit=false if:' + scope + '&&v15HeroFinisherMode==2', native_return]
    changes.update(insert)
    changes.update((cursor+i, command) for i, command in enumerate(extra))
