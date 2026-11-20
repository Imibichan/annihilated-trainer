"""Priest-route continuations entered from actual battle returns in the original game."""
from copy import copy

try:
    from . import scenes
except ImportError:
    import scenes


P2, P3, P4, P5 = (f'Scenario_Priest{n}' for n in range(2, 6))
BATTLE = 'Battle.InitializeCommand'
HEART = 'PriestHeartBladeChoice'
STRIKE = 'PriestFinalPriestRouteFinisherInput'
TIMING = 'PriestFinalPriestRouteDefaultSelected'
LOOK = dict(xSwitchChoicePriestLook=1, xSwitchChoicePriestRefuseHand=0, xSwitchPriestLowSanEnded=0,
            yValPlayerSanityRecoveryLimit=35, playerSanity=25)
REFUSE = dict(xSwitchChoicePriestLook=0, xSwitchChoicePriestRefuseHand=1, xSwitchPriestLowSanEnded=0)
AFTER_REWIND = dict(REFUSE, xSwitchPriestLowSanEnded=1, yValPlayerSanityRecoveryLimit=35,
                    playerSanity=35)


def _within(src, start, end, expected, prefix=False):
    begin = src.labels[start] if start else 0
    stop = src.labels[end] if end else len(src.text)
    matches = [i for i in range(begin, stop) if
               (src.text[i].startswith(expected) if prefix else src.text[i] == expected)]
    if len(matches) != 1:
        raise ValueError(f'僧侣回放缺少唯一原作指令 {start} / {expected}')
    return matches[0]


def _card_inputs(priest, battle):
    # Keep the stock card animations, then choose the one available mechanical action.
    for src, start, end, item, dest in (
        (priest, HEART, 'PriestHeartBladeSelected', '[cif=xSwitchPriestFinalHeartReady==1]priestLife',
         'PriestHeartBladeSelected'),
        (battle, STRIKE, TIMING, '-1', TIMING),
    ):
        button = f'@choice "{item}" button:Buttons/CustomChoiceHandlerButtonBattleCommand '
        idx = _within(src, start, end, button + f'handler:BattleCommand goto:.{dest} isTrans:false')
        stop = _within(src, start, end, '@stop')
        if idx >= stop or sum(s.startswith('@choice ') for s in src.text[src.labels[start]:stop]) != 1:
            raise ValueError(f'原作单卡演出已变化 {start}')
        yield src, idx, stop, dest


def _timing_inputs(battle):
    begin = '@summonAttackBar waitMode:"startAndWaitForStealHover" clickCount:1 stopPositionsVarName:"stopPositions"'
    end = '@summonAttackBar waitMode:"waitOnly" stopPositionsVarName:"stopPositions"'
    i = _within(battle, TIMING, 'PriestFinalBuildDestroyModeHand', begin)
    if battle.text[i+1:i+3] != [end, '@set tempSkipBattleAttackAnimation=""']:
        raise ValueError('最后一击的原作瞄准输入和清理位置已变化')
    return i, i+1


def patch_program(edits, scripts):
    """Install the isolated player's single-card inputs and battle-form initialization."""
    priest = scenes._Source(scripts[P5])
    battle = scenes._Source(scripts['Battle'])

    def append(name, idx, new_call, body):
        patch = edits.setdefault(name, {})
        if idx in patch:
            raise ValueError(f'僧侣回放指令与现有守卫冲突 {name}:{idx}')
        pos = max([len(scripts[name]), *(i+1 for i in patch)])
        patch[idx] = new_call
        patch.update({pos+n: row for n, row in enumerate(body)})

    for src, _, stop, dest in _card_inputs(priest, battle):
        name = P5 if src is priest else 'Battle'
        entry = 'V15Press' + dest
        append(name, stop, '@goto .' + entry, [
            '# ' + entry, '@goto .' + entry + 'Auto if:v15Scene>0', (name, stop),
            '# ' + entry + 'Auto', '@wait 0.5', '@goto .' + dest])
    stock_return = ('Battle', _within(battle, TIMING, 'PriestFinalBuildDestroyModeHand', '@return'))
    for n, idx in enumerate(_timing_inputs(battle)):
        entry = f'V15PriestFinalAim{n}'
        # The two waits do not feed a result into the subsequent story. The stock
        # cleanup immediately clears the bar and proceeds with its authored attack.
        append('Battle', idx, '@gosub .' + entry, [
            '# ' + entry, '@goto .' + entry + 'Done if:v15Scene>0', ('Battle', idx),
            '# ' + entry + 'Done', stock_return])
    # Battle.Start otherwise sets phase 1 even when given the real phase-2/3
    # resource explicitly. Set before the original phase-dependent partner/UI setup.
    start = _within(battle, 'Start', 'SkipBgm', '@set xGlausFinalPhase=1')
    if battle.text[start-2:start] != ['@if battleTarget=="demonLord"', '@set xGlausFinalSlot=0']:
        raise ValueError('魔王的原作形态初始化位置已变化')
    append('Battle', start, '@gosub .V15GlausPhase', [
        '# V15GlausPhase', ('Battle', start),
        '@set xGlausFinalPhase=2 if:v15Scene>0&&addEnemyResourceNames=="demonLordForm2"',
        '@set xGlausFinalPhase=3 if:v15Scene>0&&addEnemyResourceNames=="demonLordForm3"', stock_return])


def _review_flow(flow):
    """Trace verified presentation-only callbacks and the same private input replacements."""
    view = copy(flow)
    view.sources = dict(flow.sources)
    for name in (P4, P5, 'Battle'):
        src = copy(flow.sources[name])
        src.text = list(src.text)
        view.sources[name] = src
    priest, fourth, battle = (view.sources[n] for n in (P5, P4, 'Battle'))
    go = flow.sources['GameOver']
    content = [s for s in go.text[go.labels['ForPriest4Ensyutu']+1:] if s.startswith('@')]
    if len(content) != 2 or not content[0].startswith('@text "GameoverText"') or content[1] != '@return':
        raise ValueError('第四层假 Game Over 不再是可返回的原作文字演出')
    view.sources['PriestDeathText'] = go
    i = _within(fourth, 'SlimeSanLowBattleAfter', 'SlimeBattleAfterSanHigh', '@gosub GameOver.ForPriest4Ensyutu')
    fourth.text[i] = '@gosub PriestDeathText.ForPriest4Ensyutu'
    # Only these named Battle subroutines are entered as a novel. Each relative
    # jump is still traced inside the real source. Ordinary @gosub Battle retains
    # the shared first-command guard.
    view.sources['PriestBattleHelpers'] = battle
    for start, end, helper in (
        ('DemonLordBattleBefore', 'Epilogue', 'GlausFinalSetupTemporaryPartner'),
        ('PriestBattlePostBattleFinisher', 'PriestBattleHighLoopBeforeFinisher', 'PriestFinalDestroyModeDefaultWeaponPowerUp'),
        ('PriestBattleHighLoopFinisher', 'PriestBattleAfterHighLoop', STRIKE),
    ):
        i = _within(priest, start, end, '@gosub Battle.'+helper)
        priest.text[i] = '@gosub PriestBattleHelpers.'+helper
    for src, card, stop, dest in _card_inputs(priest, battle):
        src.text[card] = '@clearChoice BattleCommand'  # a presentation, never a narrative branch
        src.text[stop] = '@goto .'+dest
    _timing_inputs(battle)
    return view


def _fourth_form(flow, gallery):
    base = scenes._setup('Priest', 7, 1, dict(G_gameLoopCount=9), '') + [
        '@set backgroundName="last"', '@gosub Func.ShowBackground', '@gosub Func.ShowSettings',
        '@set xSwitchBoss5BattleEvent=1', '@set battleTarget="priest"', '@set playerStateDestroyer=1',
        '@set addEnemyResourceNames="priest"', '@set showEnemyUI=false',
    ]
    setup = base + ['@set xSwitchSystemDebugPriestPhase=3']
    commands = ['@set enemy1Health=1', '@set enemy1StateBlock=0', '@set enemy1StateBarrier=0',
                '@set enemy1StateEvading=0', '@set selectCommand=-1', '@set selectionEnemyTargetId="enemy1"']
    proof = [
        ('Battle', '@set xPriestFinalPhase=xSwitchSystemDebugPriestPhase'),
        ('Battle', '@set xPriestFinalRoute="priest"'),
        ('Battle', '@gosub .PriestFinalSetLoopBranch'),
        ('Battle', '@set priestFinalCurrentResourceName="priestForm3" if:xPriestFinalPhase==3'),
        ('Battle', '@set xPriestFinalSlot=tempBattleStartEnemyCount'),
        ('Battle', '@gosub .PriestFinalPhaseTransitionCheck if:battleTarget=="priest"'),
        ('Battle', '@return if:xPriestFinalRoute=="priest"&&xPriestFinalPhase==3&&xSwitchPriestFinalHighLoop!=1'),
        ('Battle', '@set xPriestFinalPhase=priestFinalNextPhase'),
        ('Battle', '@gosub .PriestFinalResummonEnemy'),
        ('Battle', '@set tempPriestFinalTransitionSourceId=xPriestFinalSlot'),
        ('Battle', '@if xPriestFinalRoute=="priest"&&xPriestFinalPhase==4'),
        ('Battle', '@gosub Scenario_Priest5.PriestBattleHighLoopBeforeForm4'),
        (P5, '@gosub Battle.PriestFinalUltimateTransition'),
        ('Battle', '@gosub .PriestFinalReturnToBattlePresentation'),
    ]
    record = scenes._battle_action(flow, gallery, 'Battle.Action.PriestFourthForm', 'Priest', 5,
                                  '僧侣决战 · 第四形态', setup, commands, (), proof,
                                  '第三形态进入真实战斗；自动攻击击破后触发原作变身，返回战斗至下一次出牌。')
    label = 'PriestBattleHighLoopBeforeForm4'
    src = flow.sources[P5]
    start, end = src.labels[label], src.labels['PriestBattleHighLoopAfterBreak']
    ids = [g['id'] for g in gallery if g['source'] == P5 and start < g['line'] < end]
    if not ids or any(s.startswith(('@goto ', '@if ', '@choice ')) for s in src.text[start:end]):
        raise ValueError('僧侣第四形态的原作演出发生变化')
    record['galleryIds'] = record['presets'][0]['galleryIds'] = ids
    record['presets'][0]['title'] = '击破第三形态'
    break_commands = ['@set enemy{xPriestFinalSlot}Break=0', '@set selectCommand=-1',
                      '@set selectionEnemyTargetId=GetEnemyStr(xPriestFinalSlot)']
    proof = [
        ('Battle', '@set priestFinalCurrentResourceName="priestUltimate" if:xPriestFinalRoute=="priest"&&xPriestFinalPhase>=4'),
        ('Battle', '@gosub .PriestFinalEnsureUltimateBack if:xPriestFinalRoute=="priest"'),
        ('Battle', '@if xPriestFinalRoute=="priest"&&xPriestFinalPhase>=4&&xSwitchPriestFinalBreakTextDone!=1&&enemy{xPriestFinalSlot}Death<=0&&enemy{xPriestFinalSlot}MaxBreak>0&&enemy{xPriestFinalSlot}Break<=0'),
        ('Battle', '@gosub .PriestFinalPriestRouteFinale'),
        ('Battle', '@gosub Scenario_Priest5.PriestBattleHighLoopAfterBreak'),
        ('Battle', '@gosub .PriestFinalPriestRouteBreakText'),
        ('Battle', '@gosub .PriestFinalBuildDestroyModeHand'),
        ('Battle', '@goto .PriestFinalWaitForDestroyButton if:battleBreakMode!=true'),
    ]
    after = scenes._battle_action(flow, gallery, record['id'], 'Priest', 5, record['title'],
                                 base + ['@set xSwitchSystemDebugPriestPhase=4'], break_commands, (), proof, '')
    broken = after['presets'][0]
    broken['title'] = '击破最终形态的防御'
    broken['actionAtFirstCommand']['selectBoss'] = True
    broken['exits'].append('Battle.PriestFinalBuildDestroyModeHand')
    record['exits'] = list(broken['exits'])
    record['presets'].append(broken)
    record['evidenceRows'].extend(after['evidenceRows'])
    return record


def _other_battles(flow, gallery):
    def encounter(uid, floor, title, proof, variants):
        entry = None
        for name, setup, cmds, target, exits in variants:
            record = scenes._battle_action(flow, gallery, 'Battle.Action.'+uid, 'Priest', floor,
                                          title, setup, cmds, (), proof, '战斗状态与原作事件调用链已静态核对')
            p = record['presets'][0]
            p['title'] = name
            p['actionAtFirstCommand'].update(target=target, skipTiming=(target == 'Battle.PlayerAttack'))
            p['exits'].extend(exits)
            if entry is None:
                entry = record
                entry['exits'] = list(p['exits'])
            else:
                entry['presets'].append(p)
                entry['exits'] = sorted(set(entry['exits']) | set(p['exits']))
        return entry

    dropout = [
        ('Scenario', '@set addEnemyResourceNames="dropout"'),
        ('Battle', '@if tempEnemyResourceName=="dropout"&&xSwitchDropoutForm2EventStarted!=1'),
        ('Battle', '@gosub .DropoutSecondFormTransitionCore'),
        ('Battle', '@set addEnemyResourceNames="dropoutForm2"'),
        ('Battle', '@gosub .DropoutTransformCommonBody'),
        ('Battle', '@gosub .DropoutRevealSecondForm'),
        ('Battle', '@gosub .RequestBattlePhaseRestart if:xSwitchDropoutForm2EventStarted==1&&yValDropoutForm2Slot>0&&enemy{yValDropoutForm2Slot}Death!=1'),
    ]
    variants = []
    for title, flags in (('此前拒绝伸出的手', REFUSE), ('此前看向僧侣', LOOK)):
        setup = scenes._setup('Priest', 3, 4, flags, '') + [
            '@gosub Func.ShowSettings', '@set battleTarget="dropout"', '@set addEnemyResourceNames="dropout"',
            '@set xSwitchBoss3BattleEvent=1', '@set showEnemyUI=false']
        commands = ['@set enemy1Health=1', '@set enemy1StateBlock=0', '@set enemy1StateBarrier=0',
                    '@set enemy1StateEvading=0', '@set selectCommand=-1', '@set selectionEnemyTargetId="enemy1"']
        variants.append((title, setup, commands, 'Battle.PlayerAttack', []))
    yield encounter('PriestDropout', 3, '落选者 · 第二形态', dropout, variants)

    setup = scenes._setup('Priest', 7, 1, dict(G_gameLoopCount=9), '') + [
        '@set backgroundName="last"', '@gosub Func.ShowBackground', '@gosub Func.ShowSettings',
        '@set xSwitchBoss5BattleEvent=1', '@set battleTarget="priest"', '@set addEnemyResourceNames="priest"',
        '@set playerStateDestroyer=1', '@set showEnemyUI=false', '@set xSwitchSystemDebugPriestPhase=2']
    check = '@gosub Battle.DeathCheckOnPlayer'
    # Native first-three-form gimmicks call the same two lines for success, and
    # the same two lines for failure. Use the defensive second form, which has one
    # target, then let the game's own judgment and resurrection animation run.
    proof = [
        ('Battle', '@set xSwitchPriestFinalCounterSuccessTriggered=1 if:xSwitchPriestFinalForm2StartDone==1&&enemy{xPriestFinalSlot}StateBlock<=0'),
        ('Battle', '@gosub .PriestFinalPriestRouteCounterSuccessText'),
        ('Battle', '@gosub .PriestFinalTryCurseRecoveryBeforeDeath if:battleTarget=="priest"&&xPriestFinalRoute=="priest"&&xPriestFinalSlot>0'),
        ('Battle', '@set xSwitchPriestFinalCounterFailTriggered=1 if:xPriestFinalPhase<=3&&xSwitchPriestFinalCounterSuccessTriggered!=1'),
        ('Battle', '@gosub .PriestFinalPriestRouteCounterFailText'),
        ('Battle', '@gosub .PriestFinalPriestRouteCurseRecoveryEffect'),
        ('Battle', '@gosub .PriestFinalPriestRouteDeath1Text'),
    ]
    yield encounter('PriestCounter', 5, '僧侣决战 · 破解与复生', proof, [
        ('破解防御', setup, ['@set enemy{xPriestFinalSlot}StateBlock=0', '@set selectCommand=-1',
                          '@set selectionEnemyTargetId="enemy1"'], 'Battle.PlayerAttack', []),
        ('未能破解 · 用诅咒复生', setup, ['@set curse=10', '@set playerHealth=0', check],
         'Battle.RebuildBattleCommand', []),
    ])
    proof = [
        ('Battle', '@set xSwitchPriestFinalCurseShortageGameOver=1'),
        ('Battle', '@if xSwitchPriestFinalHeroDeathFirstGameOver==1||xSwitchPriestFinalCurseShortageGameOver==1'),
        ('Battle', '@goto GameOver'),
        ('GameOver', '@gosub .PriestFinalCurseShortageGameOverEvent if:xSwitchPriestFinalCurseShortageGameOver==1'),
        ('GameOver', '@set xPriestFinalPriestRouteGameOverCount+=1'),
        ('GameOver', '@gosub .PriestFinalPriestRouteDeathGameOverText'),
        ('GameOver', '@gosub Battle.PriestFinalPriestRouteCurseShortageText'),
        *[('GameOver', f'@gosub Battle.PriestFinalPriestRouteDeath{i}Text') for i in range(2, 7)],
        ('Battle', '@return if:xSwitchPriestFinalCurseShortageTextEverShown==1'),
        ('GameOver', '# Choice'),
    ]
    shortages = []
    for i, title in enumerate(('首次', '第二次', '第三次', '第四次', '第五次', '第六次及以后')):
        cmds = [f'@set xPriestFinalPriestRouteGameOverCount={i}',
                f'@set xSwitchPriestFinalCurseShortageTextEverShown={int(i>0)}',
                '@set curse=0', '@set playerHealth=0', check]
        shortages.append((title, setup, cmds, 'Battle.RebuildBattleCommand', ['GameOver.Choice']))
    yield encounter('PriestCurseShortage', 5, '僧侣决战 · 诅咒耗尽', proof, shortages)


def _demon_lord_battles(flow, gallery):
    # Each defeated form is replaced with a healthy enemy. The game then restarts
    # the battle turn and solicits a new command, so each finisher is its own event.
    battle = flow.sources['Battle']
    for phase, (title, cg) in enumerate((
            ('放逐者与勇者', 'outcastAllyCutLight'), ('落选者与魔法师', 'dropoutAllyCutLight'),
            ('千金与战士', 'villainessAllyCutLight')), 1):
        callback = f'GlausFinalForm{phase}CounterText'
        setup = scenes._setup('Priest', 10, 1, {}, '') + [
            '@gosub Dungeon.BeforeSpecialBattleAfterChoice', '@set battleTarget="demonLord"',
            f'@set addEnemyResourceNames="demonLordForm{phase}"', '@gosub Battle.GlausFinalSetupTemporaryPartner',
            '@set xSwitchSkipBattleEndMessage=1', '@gosub Func.ShowSettings',
            '@set backgroundName="maou_gyokuza"', '@gosub Func.HideBackground', '@gosub Func.ShowBackground',
        ]
        commands = ['@set enemy{xGlausFinalSlot}Health=1', '@set enemy{xGlausFinalSlot}StateBlock=0',
                    '@set enemy{xGlausFinalSlot}StateBarrier=0', '@set enemy{xGlausFinalSlot}StateEvading=0',
                    '@set selectCommand=-1', '@set selectionEnemyTargetId=GetEnemyStr(xGlausFinalSlot)']
        proof = [
            (P5, '@gosub Battle.GlausFinalSetupTemporaryPartner'),
            ('Battle', '@set xGlausFinalSlot=tempBattleStartEnemyCount'),
            ('Battle', '@gosub .GlausFinalFormStart if:battleTarget=="demonLord"'),
            ('Battle', f'@gosub .GlausFinalForm{phase}StartText'),
            ('Battle', '@gosub .GlausFinalPhaseTransitionCheck'),
            ('Battle', '@return if:enemy{xGlausFinalSlot}Health>0&&enemy{xGlausFinalSlot}Death!=1'),
            ('Battle', f'@gosub .{callback}'),
            ('Battle', '@set xGlausFinalPhase+=1'),
            ('Battle', '@gosub .GlausFinalResummonEnemy'),
            ('Battle', '@set enemy{xGlausFinalSlot}Health=enemy{xGlausFinalSlot}MaxHealth'),
            ('Battle', '@gosub .RequestBattlePhaseRestart if:enemy{xGlausFinalSlot}ResourceName==glausFinalCurrentResourceName&&enemy{xGlausFinalSlot}Death!=1'),
        ]
        # The first CG row stages a transparent image; the gallery indexes the
        # following visible native tween. Require the exact appearance and label.
        matches = [r for r in gallery if r['source'] == 'Battle' and r['label'] == callback and
                   f'"CG/{cg}"' in battle.text[r['line']] and 'tint:"#FFFFFFFF"' in battle.text[r['line']]]
        if len(matches) != 1:
            raise ValueError('魔王战原作援护插画已变化 '+callback)
        scene = scenes._battle_action(flow, gallery, f'Battle.Action.PriestGlausForm{phase}', 'Priest', 5,
                                     '讨伐魔王 · '+title, setup, commands, (callback,), proof,
                                     '以原作队伍进入相应形态，击倒后由游戏执行援护与变身，至下次选择指令。')
        if scene['galleryIds'] != [matches[0]['id']]:
            raise ValueError('魔王战援护插画的归属已变化 '+callback)
        yield scene


def integrate(catalog_scenes, flow, gallery_rows):
    """Replace unaudited post-fight placeholders and add the missing story continuations."""
    view = _review_flow(flow)
    added = []

    def result(route, name, label, flags):
        if route['issues']:
            raise ValueError(f'僧侣回放控制流已变化 {name}.{label}: {route["issues"]}')
        ids = scenes._select_art(route['visited'], gallery_rows)
        ids.extend(scenes._ending_art(name, label, flags, route, gallery_rows))
        return ids

    def preset(name, label, title, floor, section, flags, *, story_flags=None, setup=(), preceding=None, rewind=False):
        known = dict(flags, partnerCharacter='priest')
        known.update(story_flags or {})
        stop = ('Scenario_Priest3.DropoutChoiceBefore',) if rewind else ()
        route = view.trace(name, label, known, stop, battle_exit=BATTLE)
        ids = result(route, name, label, known)
        choices = route['choices']
        if preceding:
            prior = view.trace(name, preceding, known, battle_exit=BATTLE)
            if not prior['returns'] or prior['exits']:
                raise ValueError('僧侣终击没有返回原作告别流程')
            ids = result(prior, name, preceding, known) + ids
            choices += prior['choices']
        if rewind:
            if route['exits'] != list(stop):
                raise ValueError('第四层坏结局没有返回第三层原作分歧')
            later = dict(known, xSwitchPriestLowSanEnded=1, xSwitchChoicePriestLook=0)
            route = view.trace(P3, 'DropoutChoiceBefore', later, battle_exit=BATTLE)
            ids.extend(result(route, P3, 'DropoutChoiceBefore', later))
            choices += route['choices']
        commands = scenes._setup('Priest', floor, section, flags, label)
        if 'yValPlayerSanityRecoveryLimit' in flags:
            commands.append('@set xSwitchPlayerSanityRecoveryLimited=true')
        commands.extend(setup)
        exits = [x for x in route['exits'] if x != '@title']
        return dict(title=title, status='script-reviewed', setupCommands=commands, exits=exits,
                    naturalReturn=route['returns'], naturalTitle='@title' in route['exits'], issues=[],
                    choices=choices, galleryIds=list(dict.fromkeys(ids)))

    def add(name, label, chapter, title, presets):
        first = presets[0]
        exits = sorted({s for p in presets for s in p['exits']})
        added.append(dict(id=name+'.'+label, source=name, label=label, group='Priest', chapter=chapter,
                          title=title, line=flow.sources[name].labels[label], presets=presets,
                          setupCommands=first['setupCommands'], exits=exits, status='script-reviewed',
                          naturalReturn=any(p['naturalReturn'] for p in presets),
                          naturalTitle=any(p['naturalTitle'] for p in presets),
                          boundary='return' if first['naturalReturn'] and not exits else 'label',
                          galleryIds=list(dict.fromkeys(s for p in presets for s in p['galleryIds'])),
                          evidence='原作战后回调、分歧条件及返回路径已静态核对'))

    p2 = flow.sources[P2]
    _within(p2, 'SentakusiMisuteru', 'MageHeroBattleAfter', '@set battleTarget="mage"')
    _within(p2, 'SentakusiMisuteru', 'MageHeroBattleAfter', '@set battleTarget="hero"')
    _within(p2, 'SkipNaiEnsyutu', 'SentakusiMisuteru', '@goto .VillainessBattleAfter')
    add(P2, 'MageHeroBattleAfter', 2, '舍弃伙伴之后', [
        preset(P2, 'MageHeroBattleAfter', '背弃伙伴', 2, 4, dict(xSwitchPriestNakamaMisuteru=1, playerSanity=0),
               setup=['@stopBgm', '@set backgroundName="cave_moss"', '@gosub Func.HideBackground',
                      '@gosub Func.ShowBackground', '@sfx fs_heartbeat loop:true pitch:1.5',
                      '@changeVolume Vignette from:0 value:0.5 time:2 loop:true wait:false ui:false',
                      '@gosub Dungeon.AfterSpecialChoice'])])
    add(P2, 'VillainessBattleAfter', 2, '千金战后 · 关于那颗头颅', [
        preset(P2, 'VillainessBattleAfter', '拒绝舍弃伙伴', 2, 4, dict(xSwitchBosChokuzenDekinai=1),
               setup=['@gosub Dungeon.BeforeNovelHideUIWithoutMenu'])])
    add(P3, 'EliteBattle3After', 3, '海龙战后', [
        preset(P3, 'EliteBattle3After', '击退海龙', 3, 3, {}, setup=['@gosub Dungeon.BeforeNovelHideUIWithoutMenu'])])
    variants = [('拒绝伸出的手', REFUSE), ('看向僧侣', LOOK), ('经历过第四层的结局', AFTER_REWIND)]
    repeated = dict(REFUSE, G_gameLoopCount=9, G_gameOverPriestPartnerCount=1,
                    G_gameClearHeroCount=1, G_gameKilledByPriestCount=1)
    add(P4, 'ToDungeon4', 4, '前往第四层 · 僧侣的回忆', [
        preset(P4, 'ToDungeon4', t, 3, 5, f)
        for t, f in (*variants[:2], ('记得此前的死亡与通关', repeated))])
    add(P4, 'Slime3BattleAfter', 4, '巨人战后', [
        preset(P4, 'Slime3BattleAfter', t, 4, 3, f, setup=['@gosub Dungeon.BeforeNovelHideUIWithoutMenu'])
        for t, f in variants])
    add(P4, 'SlimeBattleAfter', 4, '史莱姆战后', [
        preset(P4, 'SlimeBattleAfter', t, 4, 4, f, rewind=bool(f['xSwitchChoicePriestLook']),
               story_flags={'xSwitchEndingResumeStory': 1, 'endingType': 'priest4KilledBad'},
               setup=['@gosub Dungeon.BeforeNovelHideUIWithoutMenu']) for t, f in variants[:2]])
    add(P4, 'defaultSlimeBattleAfter', 4, '最后的史莱姆 · 救援与旁观', [
        preset(P4, 'defaultSlimeBattleAfter', t, 4, 4, f,
               story_flags={'xSwitchEndingResumeStory': 0, 'endingType': 'priest4NoReachBad'},
               setup=['@set showPartnerStatus=true', '@set partnerDeath=0', '@set partnerHealth=1',
                      '@gosub Dungeon.BeforeSpecialBattleAfterChoice'])
        for t, f in (('首次来到这里', REFUSE), ('经历过第四层的结局', AFTER_REWIND))])
    add(P5, 'DemonLordBattleBefore', 5, '讨伐魔王 · 决战开场', [
        preset(P5, 'DemonLordBattleBefore', '与勇者小队同行', 10, 1, {})])
    high = dict(G_gameLoopCount=9, xSwitchPriestFinalHighLoop=1, xSwitchPriestFinalDestroyModeDone=1,
                xSwitchPriestFinalDestroyModeFinishTextDone=0)
    add(P5, 'PriestBattleAfterHighLoop', 6, '最后一击与告别', [
        preset(P5, 'PriestBattleAfterHighLoop', '高周目决战之后', 7, 1, high,
               story_flags={'xPriestFinalRoute': 'priest', 'xSwitchEndingResumeStory': 0, 'endingType': 'priestHighLoop'},
               preceding='PriestBattlePostBattleFinisher',
               setup=['@set backgroundName="last"', '@gosub Func.HideBackground', '@gosub Func.ShowBackground',
                      '@set xPriestFinalRoute="priest"', '@set xPriestFinalPhase=4',
                      '@gosub Scenario_Priest5.PriestBattlePostBattleFinisher',
                      '@set xSwitchCanSelectAnyItemByTurn=0', '@gosub Dungeon.BeforeSpecialBattleAfterChoice',
                      '@back black id:ColorFlashBackground tint:#FFFFFFFF time:1 pos:,,-15.5 scale:9999999 wait:false',
                      '@wait i1'])])
    added.append(_fourth_form(flow, gallery_rows))
    added.extend(_other_battles(flow, gallery_rows))
    positions = {s['id']: i for i, s in enumerate(catalog_scenes)}
    for entry in added:
        if entry['id'] in positions:
            catalog_scenes[positions[entry['id']]] = entry
        else:
            catalog_scenes.append(entry)
    demon = list(_demon_lord_battles(flow, gallery_rows))
    ids = {s['id'] for s in demon}
    catalog_scenes[:] = [s for s in catalog_scenes if s['id'] not in ids]
    after = next(i for i, s in enumerate(catalog_scenes) if s['id'] == P5+'.DemonLordBattleBefore') + 1
    catalog_scenes[after:after] = demon
