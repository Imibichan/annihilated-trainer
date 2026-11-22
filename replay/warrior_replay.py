"""Verified Warrior story callbacks, including the scripted game-over round trip."""
from copy import copy

try:
    from .scenes import _battle_action, _select_art, _ending_art, _setup
except ImportError:
    from scenes import _battle_action, _select_art, _ending_art, _setup


S2 = 'Scenario_Warrior2'
S4 = 'Scenario_Warrior4'
S5 = 'Scenario_Warrior5'
COMMAND = 'Battle.InitializeCommand'
AFTER_SERVANTS = 'V15SlimeServantsAfter'


def _proof(flow, source, start, commands):
    src = flow.sources[source]
    position = src.labels[start] if start else 0
    rows = []
    for command in commands:
        try:
            line = src.text.index(command, position)
        except ValueError as exc:
            raise ValueError(f'战士回放的原作流程已变化 {source}.{start} {command}') from exc
        rows.append(dict(source=source, line=line, text=command))
        position = line + 1
    return rows


def _slime_post_slot(lines, kinds, section):
    anchor = '@set battleTarget="warrior4SlimeServants"'
    lo, hi = lines.index('# Slime'+str(section)), lines.index('# Slime'+str(section+1))
    if lines[lo:hi].count(anchor) != 1:
        raise ValueError('仆从战入口已变化')
    i = lines.index(anchor, lo, hi) + 1
    if lines[i:i+2] != ['@gosub Battle', '@gosub Dungeon.BeforeNovelHideUI'] or kinds[i+2] not in ('Empty', 'Comment'):
        raise ValueError('仆从战后的剧情回调已变化')
    return i + 2


def patch_program(edits, scripts, active_ids=None):
    """Expose the original fallthrough after the servants' fight without moving story rows."""
    for section, name in [(2, AFTER_SERVANTS), (1, 'V15FallenRescuersAfter')]:
        if active_ids is not None and S4 + '.' + name not in active_ids:
            continue
        rows = scripts[S4]
        patch = edits.setdefault(S4, {})
        i = _slime_post_slot([r[3].strip() for r in rows], [r[1] for r in rows], section)
        label = '# ' + name
        if i in patch and patch[i] != label:
            raise ValueError('仆从战后入口与其他回放修改重叠')
        patch[i] = label
    # A marker is emitted in each selected first-turn bridge. Scope the extra
    # controls to the actual directory flag; a title restart needs no cleanup.
    flags = {}
    active = None
    for _, row in sorted(edits.get('Test2', {}).items()):
        if isinstance(row, str) and row.startswith('# '):
            active = row[9:] if row.startswith('# Trigger') else None
        if active and row in ('@set v15WarriorArms=1', '@set v15WarriorHydra=1'):
            flags.setdefault(row, []).append(int(active))
    if not flags:
        return
    lines = [r[3].strip() for r in scripts['Battle']]
    patch = edits.setdefault('Battle', {})
    cursor = max([len(lines)] + [i+1 for i in patch])
    def append(rows):
        nonlocal cursor
        for row in rows:
            patch[cursor] = row
            cursor += 1
    for side, card in [('Left', -40), ('Right', -41)]:
        if '@set v15WarriorArms=1' not in flags:
            break
        entry = 'SlimeWarrior'+side+'Hand'
        start, end = lines.index('# '+entry+'Choice'), lines.index('# '+entry+'Selected')
        stop = start + lines[start:end].index('@stop')
        if stop in patch or not any(f'value:"{card}" goto:.{entry}Selected' in t for t in lines[start:end]):
            raise ValueError('战士左右手的原作输入已变化')
        patch[stop] = '@goto .V15'+side+'Arm'
        append(['# V15'+side+'Arm'] + [f'@goto .V15{side}ArmInput if:v15Scene=={flag}'
                                        for flag in flags['@set v15WarriorArms=1']] +
               [('Battle', stop), '# V15'+side+'ArmInput', '@set z=EnableBattleBreakModeWithFeedback()',
                f'@set selectCommand={card}', '@goto .'+entry+'Selected'])
    if '@set v15WarriorHydra=1' in flags:
        start = lines.index('# WarriorIllusionBReturnAfterHydra')
        i = lines.index('@gosub .WarriorIllusionBAfterHydraText', start) + 1
        if scripts['Battle'][i][1] not in ('Empty', 'Comment') or i in patch:
            raise ValueError('九头蛇战后的回合入口已变化')
        condition = '||'.join(f'v15Scene=={f}' for f in flags['@set v15WarriorHydra=1'])
        patch[i] = '@gosub .V15HydraLastTurn if:'+condition
        append(['# V15HydraLastTurn', '@set turnCount=Max(8,yValWarriorIllusionBAfterHydraReturnTurn+2)',
                '@set tempWarriorIllusionEventTiming="turnStart"', '@gosub .WarriorIllusionBattleEventCheck',
                ('Battle', lines.index('@return', i))])


def _entry(flow, gallery, source, label, chapter, section, title, variants, *, prepare=(),
           known=None, trace_func=None, evidence=()):
    presets = []
    for variant, flags in variants:
        state = dict(flags, partnerCharacter='warrior')
        state.update(known or {})
        route = (trace_func(state) if trace_func else
                 flow.trace(source, label, state, battle_exit=COMMAND))
        if route['issues'] or not (route['returns'] or route['exits']):
            raise ValueError(f'战士回放未定位出口 {source}.{label} {route["issues"]}')
        commands = _setup('Warrior', 6 if source == S5 else int(source[-1]), section, flags, label)
        commands.extend(prepare)
        ids = _select_art(route['visited'], gallery)
        ids.extend(_ending_art(source, label, flags, route, gallery))
        presets.append(dict(title=variant, setupCommands=commands, exits=[x for x in route['exits'] if x != '@title'],
                            naturalTitle='@title' in route['exits'], naturalReturn=route['returns'], choices=route['choices'],
                            galleryIds=ids, status='script-reviewed', issues=[]))
    first = presets[0]
    return dict(id=source+'.'+label, group='Warrior', chapter=chapter, source=source, label=label,
                line=flow.sources[source].labels[label], title=title, presets=presets,
                setupCommands=first['setupCommands'], exits=sorted({x for p in presets for x in p['exits']}),
                naturalReturn=any(p['naturalReturn'] for p in presets), naturalTitle=any(p['naturalTitle'] for p in presets),
                galleryIds=list(dict.fromkeys(x for p in presets for x in p['galleryIds'])),
                status='script-reviewed', boundary='return' if first['naturalReturn'] else 'label',
                evidence='原作事件条件、对话分支与回放边界已按脚本核对', evidenceRows=list(evidence))


ALONE = ('@gosub Func.ClearPartnerCharacter', '@set showPartnerStatus=false')


def _companion(name, level):
    return [f'@set switchPartnerCharacter="{name}"', '@gosub Func.ChangePartnerCharacter',
            f'@set tempTargetLv={level}', '@set tempCharacter="partner"',
            '@gosub StatusFunc.StatusSettingForceLvSafe', '@set partnerHealth=partnerMaxHealth',
            '@set showPartnerStatus=true', '@gosub Func.SavePartnerCharacterState']


def _stop_battle(flow, gallery):
    setup = _setup('Warrior', 6, 5, {}, '') + list(ALONE) + [
        '@set backgroundName="maou_gyokuza"', '@gosub Func.ShowBackground', '@gosub Func.ShowSettings',
        '@set battleTarget="warriorFinalDuel"', '@set addEnemyResourceNames="warriorFinal"',
        '@set showEnemyUI=false']
    # Replay the turn after the sixth recovery. The native preparation unlocks the
    # card and narrates why the protagonist stops fighting. PlayerAttack runs both cuts.
    commands = ['@set yValWarriorDefeatOrBreakCount=6', '@gosub Battle.WarriorFinalDuelOwariPrepareEvent',
                '@set playerHealth=1', '@set playerStateBlock=0', '@set playerStateBarrier=0',
                '@set selectCommand=-141']
    proof = [
        (S5, '@set battleTarget="warriorFinalDuel"'),
        ('Battle', '@set xSwitchWarriorFinalStopUnlockPending=1 if:yValWarriorDefeatOrBreakCount>=6&&xSwitchWarriorFinalStopCardEnabled!=1'),
        ('Battle', '@gosub .WarriorFinalDuelOwariPrepareEvent'),
        ('Battle', '@set xSwitchWarriorFinalStopCardEnabled=1'),
        ('Battle', '@if battleTarget=="warriorFinalDuel"&&xSwitchWarriorFinalStopCardEnabled==1&&turnCharacter=="player"&&forwardCharacter=="player"'),
        ('Battle', '@set actionNumber="-141"'), ('Battle', '@gosub .ShowMagic'),
        ('Battle', '@set z=SetNowBattleActionSetAndGetActionSetName("item",selectCommand)'),
        ('Battle', '@if battleTarget=="warriorFinalDuel"&&nowBattleActionSetName=="warriorStopBattle"'),
        ('Battle', '@gosub .WarriorFinalStopBattleText1'),
        ('Action', '@if battleTarget=="warriorFinalDuel"&&nowBattleActionSetName=="warriorStopBattle"&&actionTargetId=="player"&&actionValue>0'),
        ('Battle', '@if battleTarget=="warriorFinalDuel"&&playerHealth<=0&&xSwitchWarriorFinalStopCardUsed==1'),
        ('Battle', '@goto .WarriorFinalStopBattleEnd'), ('Battle', '@gosub .WarriorFinalStopBattleText2'),
        ('Battle', '@goto Scenario_Warrior5.WarriorBattleAfter')]
    record = _battle_action(flow, gallery, 'Battle.Action.WarriorStopBattle', 'Warrior', 6,
                            '战士决战 · 终止战斗', setup, commands,
                            ('WarriorFinalStopBattleText1', 'WarriorFinalStopBattleText2'), proof,
                            '第六次复起后的原作特殊指令与生命归零判定，引出决战的两段演出。')
    record['exits'].append(S5+'.WarriorBattleAfter')
    return record


def _illusion_approach(flow, gallery, number, companion, level):
    kind = 'ABC'[number-1]
    label = 'Last'+str(number)
    attack = ('warriorIllusionAGrandAttack', 'warriorHydraPoisonBlast', 'warriorIllusionCGrandAttack')[number-1]
    flags = [('援军赶到', {'xSwitchWarriorFinalRescueAvailable': 1, 'xSwitchChoiceOutcastFinalB': 0}),
             ('同伴独自掩护', {'xSwitchWarriorFinalRescueAvailable': 0, 'xSwitchChoiceOutcastFinalB': 1})]
    preparation = _companion(companion, level) if number < 3 else list(ALONE)
    state = 'warriorIllusion'+kind
    proof = _proof(flow, S5, label, [f'@set battleTarget="{state}"', '@gosub Battle'])
    proof += _proof(flow, 'Battle', 'EnemiesActionLoop', [
        '@set tempWarriorIllusionEventTiming="beforeEnemyAction"',
        '@gosub .WarriorIllusionBattleEventCheck if:IsSplitIn("warriorIllusionA,warriorIllusionB,warriorIllusionC",battleTarget)'])
    check = flow.sources['Battle'].text
    if not any(t.startswith('@if tempWarriorIllusionEventTiming=="beforeEnemyAction"') and
               f'tempWarriorIllusionNextActionName=="{attack}"' in t for t in check):
        raise ValueError('幻影的援军触发招式已变化 '+attack)
    title = ('第一道幻影 · 魔法师与落选者', '第二道幻影 · 九头蛇的毒息', '第三道幻影 · 僧侣与反派千金')[number-1]
    record = _entry(flow, gallery, S5, label, 5, number+1, title, flags,
                    prepare=preparation, evidence=proof)
    turns = ['@set tempWarriorIllusionEventTiming="turnStart"', '@set turnCount=2',
             '@gosub Battle.WarriorIllusionBattleEventCheck',
             '@set turnCount=4' if number == 2 else '@set turnCount=3',
             '@gosub Battle.WarriorIllusionBattleEventCheck']
    enemy = 'yValWarriorHydraEnemyId' if number == 2 else '1'
    action = dict(commands=turns + [f'@set v15WarriorEnemy={enemy}',
                  f'@storeEnemyNextActionSet enemyId:{{v15WarriorEnemy}} actionSetName:"{attack}"',
                  '@set tempEnemyId=v15WarriorEnemy'], target='Battle.EnemiesActionLoop')
    for i, preset in enumerate(record['presets']):
        preset['actionAtFirstCommand'] = action
        if number == 2:
            cuts = ['WarriorIllusionBStartText', 'WarriorIllusionBStartText2']
            if i == 0:
                cuts.append('WarriorIllusionOutcastRescueText')
            preset['galleryIds'].extend(r['id'] for r in gallery if r['source']=='Battle' and r['label'] in cuts)
    record['galleryIds'] = list(dict.fromkeys(x for p in record['presets'] for x in p['galleryIds']))
    return record


def _other_battles(flow, gallery):
    def prep(floor, section, target, enemies):
        return _setup('Warrior', floor, section, {}, '') + ['@gosub Func.ShowSettings',
                f'@set battleTarget="{target}"', f'@set addEnemyResourceNames="{enemies}"', '@set showEnemyUI=false']
    hydra_setup = prep(6, 3, 'warriorIllusionB', 'warriorIllusionB') + _companion('hero', 16)
    with flow.review('Battle.Action.WarriorHydraAfter'):
        hydra = _battle_action(flow, gallery, 'Battle.Action.WarriorHydraAfter', 'Warrior', 5, '九头蛇倒下之后',
            hydra_setup, ['@set v15WarriorHydra=1', '@set turnCount=4', '@set tempWarriorIllusionEventTiming="turnStart"',
            '@gosub Battle.WarriorIllusionBattleEventCheck', '@set enemy{yValWarriorHydraEnemyId}StateImmortal=0',
            '@set enemy{yValWarriorHydraEnemyId}StateImmuneDeath=0', '@set enemy{yValWarriorHydraEnemyId}StateBlock=0',
            '@set enemy{yValWarriorHydraEnemyId}StateEvading=0', '@set enemy{yValWarriorHydraEnemyId}Health=1',
            '@set selectionEnemyTargetId=GetEnemyStr(yValWarriorHydraEnemyId)', '@set selectCommand=-1'],
            ('WarriorIllusionHydraDefeatedText','WarriorIllusionBAfterHydraText','WarriorIllusionBAfterHydraText4'),
            [('Battle','@gosub .WarriorIllusionBStartText3'), ('Battle','# WarriorIllusionHydraAppear'),
             ('Battle','@set yValWarriorHydraEnemyId=enemyMaxCount'),
             ('Battle','@if battleTarget=="warriorIllusionB"&&tempEnemyResourceName=="warriorHydraIllusion"'),
             ('Battle','@gosub .WarriorIllusionHydraDefeatedText'), ('Battle','@gosub .WarriorIllusionBReturnAfterHydra'),
             ('Battle','@set yValWarriorIllusionBAfterHydraReturnTurn=turnCount'),
             ('Battle','@gosub .WarriorIllusionBAfterHydraText4')], '真实九头蛇对象被击倒，再续原作幻影回合对白。')
        yield hydra

    head_setup = prep(2, 4, 'villainess', 'villainess') + ['@set xSwitchVillainessBattleRe=1',
                    '@set xSwitchVillainessWithDollDamageFirstEvent=1', '@set xSwitchSkipEnemyAppearMessage=1']
    cmds = ['@set addItem="warriorHead"', '@gosub Func.AddItem', '@set selectCommand=itemAddedIndex',
            '@set tempReduceAmount=Max(0,GetItemDurabilityBySlotNumber(selectCommand)-1)',
            '@set z=ReduceItemDurability(selectCommand,tempReduceAmount,true)', '@set battleBreakMode=true',
            '@set turnCharacter="partner"', '@set turnCharacterId="partner"', '@set notTurnCharacter="player"',
            '@set turnCharacterPosition=GetTargetCharacterPosition(turnCharacter)', '@set notTurnCharacterPosition="front"',
            '@set notTurnCharacterPosition="back" if:turnCharacterPosition=="front"', '@set selectionEnemyTargetId="enemy1"']
    with flow.review('Battle.Action.WarriorHead'):
        head = _battle_action(flow, gallery, 'Battle.Action.WarriorHead', 'Warrior', 2, '战士投出的头颅', head_setup, cmds,
            ('WarriorHeadThrowPresentation', 'WarriorHeadVillainessHitPresentation'),
            [('Func','@addItem "{addItem}" AddedIndexSaveValue:"itemAddedIndex"'),
             ('Battle','@if nowBattleActionSetName=="warriorHead"&&battleTarget=="villainess"'),
             ('Battle','@set xSwitchWarriorAtamaBreak=1'), ('Battle','@gosub .WarriorHeadThrowPresentation'),
             ('Battle','@return if:turnCharacter!="partner"||partnerCharacter!="warrior"'),
             ('Battle','@gosub .WarriorHeadVillainessHitPresentation'), ('Battle','@gosub BreakItem'),
             ('Battle','@set xSwitchBattleEndRequested=1')], '战士使用原作物品槽的最后一次耐久，触发投掷与命中两段演出。')
        yield head

    arms_setup = prep(4, 4, 'slime', 'slimeForm3Me') + ['@set xSwitchSystemDebugSlimePhase=3']
    arms_cmd = ['@set v15WarriorArms=1','@set yValSlimeWarriorReviveCount=3',
                '@set actionTargetId=GetEnemyStr(xSlimeSlot)', '@gosub Battle.SlimeWarriorRememberBodyBeforeSteal',
                '@gosub Battle.SlimeRevealAfterBodySteal', '@gosub Battle.SlimePhase3EndBranch']
    with flow.review('Battle.Action.WarriorArms'):
        arms = _battle_action(flow, gallery, 'Battle.Action.WarriorArms', 'Warrior', 4, '战士的左手与主角的右手',
            arms_setup, arms_cmd, ('SlimeWarriorRightHandSelected',),
            [('Battle','@if battleTarget=="slime"&&xSwitchSystemDebugSlimePhase==3&&enemy{tempBattleStartEnemyCount}ResourceName=="slimeForm3Me"'),
             ('Battle','@return if:enemy{xSlimeSlot}ResourceName!="slimeForm3Me"'),
             ('Battle','@set xSwitchSlimeWarriorSpecialTriggered=1 if:partnerCharacter=="warrior"'),
             ('Battle','@goto .SlimeWarriorSpecialBranch if:partnerCharacter=="warrior"'),
             ('Battle','@if yValSlimeWarriorReviveCount>=3'), ('Battle','@goto .SlimeWarriorCombinationAttack'),
             ('Battle','# SlimeWarriorLeftHandChoice'),('Battle','# SlimeWarriorRightHandChoice'),
             ('Battle','@set enemy{xSlimeSlot}Death=1')], '在第三形态重现身体被夺后的剧情。两只手依次使用原本的破坏模式指令。')
        preset = arms['presets'][0]
        arms['presets'] = [dict(preset, title=title, actionAtFirstCommand=dict(
            target=COMMAND, commands=['@set playerHealth='+hp] + arms_cmd)) for title,hp in [
                ('主角毫发无伤', 'playerMaxHealth'), ('主角负伤', 'Ceiling(playerMaxHealth*0.6)'), ('主角重伤', '1')]]
        arms['actionAtFirstCommand'] = arms['presets'][0]['actionAtFirstCommand']
        yield arms


def _game_over_route(flow):
    # GameOver is normally opaque to the shared tracer (ordinary deaths can open a shop
    # or load a save). Follow just this native mode and require its sole outgoing target.
    # The aliases below are local to verification. No game-over script is patched.
    flags = dict.fromkeys('xSwitchTutorialSlimeBattle xSwitchTutorialCurseUsage xSwitchIsTutorial '
                          'xSwitchPriestFinalHeroRetryBattle xSwitchPriestFinalCurseShortageRetryBattle '
                          'xSwitchPriestFinalHeroDeathFirstGameOver xSwitchPriestFinalCurseShortageGameOver '
                          'xSwitchPriestFinalMageDeathCurseGameOver xSwitchPriestFinalSkipGameOverVisual '
                          'xSwitchWarriorFinalRetryBattle xSwitchWarriorLv1DuelRetryBattle '
                          'xSwitchWarriorFinalDefeatGameOver yValHeroRebattleRestoreStage'.split(), 0)
    flags['G_xSwitchFirstDeadOnPriestEventEnd'] = 1
    start = 'GameOverBackPoint'
    evidence = _proof(flow, S5, 'WarriorBattleAfter', [
        '@gosub Func.ChangePartnerCharacter', '@gosub Func.SaveStatusToSub',
        '@set xSwitchWarrior5LvUpGameOver=1', '@goto GameOver'])
    evidence += _proof(flow, 'GameOver', 'gameover', [
        '@gosub Dungeon.afterEvent', '@gosub .GameOverBeforeCore', '@if xSwitchWarrior5LvUpGameOver==1',
        '@goto .GameOverEnd', '# GameOverEnd', '@gosub .GameOverAfterReset',
        '@if xSwitchWarrior5LvUpGameOver==1', '@goto Scenario_Warrior5.GameOverBackPoint'])
    evidence += _proof(flow, S5, start, ['@gosub StatusFunc.LvUpOnWarrior5',
        '@gosub Func.ResetStatusToLv1', '@goto .AfterToLv1', '# AfterToLv1',
        '@set battleTarget="warriorLv1Duel"', '@gosub Battle'])
    scoped = copy(flow)
    scoped.sources = flow.sources.copy()
    gameover = copy(flow.sources['GameOver'])
    assert_zero = '@elseif yValHeroRebattleRestoreStage>0'
    _proof(flow, 'GameOver', 'GameOverBeforeCore', [assert_zero])
    # The verifier supports equality tests. With this explicitly initialized value the
    # unconnected Hero-only restoration arm is false throughout this subroutine.
    gameover.text = ['@elseif false' if t == assert_zero else
                     '@gosub WarriorReplayDungeon.afterEvent' if t == '@gosub Dungeon.afterEvent' else t
                     for t in gameover.text]
    scoped.sources['WarriorReplayDungeon'] = flow.sources['Dungeon']
    scoped.sources['WarriorReplayGameOver'] = gameover
    jump = S5 + '.' + start
    mode = dict(flags, dungeonId=6, sectionId=5, partnerCharacter='warrior', xSwitchWarrior5LvUpGameOver=1)
    middle = scoped.trace('WarriorReplayGameOver', 'gameover', mode, boundaries=(jump,))
    if middle['issues'] or middle['choices'] or middle['returns'] or middle['exits'] != [jump]:
        raise ValueError(f'战士的假性全灭分支已变化 {middle["issues"]}')

    def trace(state):
        before = flow.trace(S5, 'WarriorBattleAfter', state, boundaries=('GameOver',))
        if before['issues'] or before['exits'] != ['GameOver'] or before['returns']:
            raise ValueError('战士决战战后没有进入原作全灭流程')
        after = flow.trace(S5, start, state, battle_exit=COMMAND)
        if after['exits'] != [COMMAND] or after['returns']:
            raise ValueError('一级决斗入口已变化')
        after['visited'][S5].update(before['visited'][S5])
        after['visited']['GameOver'] = middle['visited']['WarriorReplayGameOver']
        return after
    return flags, evidence, trace


def integrate(catalog_scenes, flow, gallery_rows):
    """Add or replace native menu records in place, before the shared coverage calculation."""
    entries = []
    plain = [('原作入口', {})]
    court = []
    for letter, title in zip('ABCDE', ('曾决定放过放逐者', '曾决定杀死放逐者', '当时无法决定',
                                       '曾要求正式审判', '曾把决定交给战士')):
        flags = {'xSwitchChoiceOutcastFinal'+key: int(key == letter) for key in 'ABCDE'}
        court.append((title, dict(flags, xSwitchWarriorAtamaBreak=0)))
    court.append(('战斗中击碎了头颅（此前选择放过）', dict(court[0][1], xSwitchWarriorAtamaBreak=1)))
    with flow.review(S2+'.VillainessBattleAfter'):
        entries.append(_entry(flow, gallery_rows, S2, 'VillainessBattleAfter', 2, 4, '战后裁决 · 前未婚妻', court,
                              prepare=('@gosub Dungeon.BeforeSpecialBattleAfterChoice',),
                              evidence=_proof(flow, S2, 'VillainessBattleAfter', [
                                  '@if xSwitchWarriorAtamaBreak==1', '# ChoiceWarriorBattleAfterKutsugaesuS',
                                  '@set xSwitchChoiceWarriorBattleAfterKutsugaesuS=1',
                                  '@goto .KorosanaiPoint if:xSwitchChoiceOutcastFinalB!=1'])))
    with flow.review(S2+'.DealerBattleAfter'):
        entries.append(_entry(flow, gallery_rows, S2, 'DealerBattleAfter', 2, 3, '荷官战后 · 未曾说出的解释', plain,
                              prepare=('@gosub Dungeon.BeforeSpecialBattleAfterChoice',),
                              evidence=_proof(flow, S2, 'Villainess3', ['@gosub Scenario.DealerBattleCore',
                                          '@gosub Dungeon.BeforeSpecialBattleAfterChoice', '# DealerBattleAfter'])))
    with flow.review(S4+'.Slime2'):
        entries.append(_entry(flow, gallery_rows, S4, 'Slime2', 4, 2, '幻象与战士的绿光剑', plain,
                              evidence=_proof(flow, S4, 'Slime2', ['@gosub Dungeon.ResetRouletteState',
                                          '# RouletteStop', '# ClearButtonAfter', '@set xSwitchWarriorDestroyMode=1',
                                          '@set battleTarget="warrior4SlimeServants"', '@gosub Battle'])))

    def after_servants(section, label):
        src = flow.sources[S4]
        scoped = copy(flow)
        scoped.sources = flow.sources.copy()
        added = copy(src)
        added.labels = dict(src.labels)
        added.labels[label] = _slime_post_slot(src.text, src.kinds, section)
        scoped.sources[S4] = added
        return scoped
    with flow.review(S4+'.V15FallenRescuersAfter'):
        scoped = after_servants(1, 'V15FallenRescuersAfter')
        entries.append(_entry(scoped, gallery_rows, S4, 'V15FallenRescuersAfter', 4, 1, '昔日救援队的亡骸', plain,
                              evidence=_proof(flow, S4, 'Slime1', ['@gosub Battle', '@gosub Dungeon.BeforeNovelHideUI',
                                                                     '@return'])))
    with flow.review(S4+'.'+AFTER_SERVANTS):
        scoped = after_servants(2, AFTER_SERVANTS)
        entries.append(_entry(scoped, gallery_rows, S4, AFTER_SERVANTS, 4, 2, '仆从战后 · 战士的觉醒', plain,
                              prepare=('@set xSwitchWarriorDestroyMode=1',),
                              evidence=_proof(flow, S4, 'Slime2', ['@gosub Battle', '@gosub Dungeon.BeforeNovelHideUI',
                                          '# KakuseiCutTest', '@set learnTargetSwitch="xSwitchWarriorDestroyMode"',
                                          '@gosub Func.Learn', '@return'])))
    with flow.review(S4+'.GiantBattleAfter'):
        entries.append(_entry(flow, gallery_rows, S4, 'GiantBattleAfter', 4, 3, '巨人战后的交谈', plain,
                              prepare=('@gosub Dungeon.BeforeNovelHideUIWithoutMenu',),
                              evidence=_proof(flow, S4, 'Slime3', ['@gosub Scenario.GiantBattleCore',
                                                                   '# GiantBattleAfter', '@return'])))

    arrivals = [('援军及时赶到', {'xSwitchWarriorFinalHelpArrived': 1}),
                ('援军未赶到', {'xSwitchWarriorFinalHelpArrived': 0})]
    for n, who, level, title in [(1, 'mage', 14, '第一道幻影之后 · 与魔法师道别'),
                                  (2, 'hero', 16, '第二道幻影之后 · 勇者与放逐者'),
                                  (3, 'priest', 28, '第三道幻影之后 · 与僧侣道别')]:
        with flow.review(f'{S5}.Last{n}'):
            entries.append(_illusion_approach(flow, gallery_rows, n, who, level))
        label = f'Last{n}BattleAfter'
        with flow.review(S5+'.'+label):
            entries.append(_entry(flow, gallery_rows, S5, label, 5, n+1, title, arrivals,
                                  prepare=_companion(who, level),
                                  evidence=_proof(flow, S5, f'Last{n}', ['@gosub Battle', '# '+label,
                                              '@if xSwitchWarriorFinalHelpArrived==1'])))

    beliefs = []
    for key, title in [('Yokatta', '曾庆幸获救'), ('Uramu', '曾怨恨自己被救'),
                       ('Shikatanai', '曾认为别无选择')]:
        flags = {'xSwitchChoiceSaikyouHuman'+k: int(k == key) for k in ('Yokatta','Uramu','Shikatanai')}
        beliefs.append((title, flags))
    # The original flips xSwitchWarriorGlitchEnd and re-enters its own dialogue. Do not
    # treat this mutable flag as an immutable input to the trace or replace the choices.
    with flow.review(S5+'.WarriorBattleBefore'):
        decision_proof = _proof(flow, S5, 'WarriorBattleBefore', ['# WarriorChoiceBefore', '# WarriorTomeru2',
            '@set battleTarget="warriorFinalDuel"', '@gosub Battle', '# WarriorGlitchEnd',
            '@set xSwitchWarriorGlitchEnd=1', '@set endingType="warriorGlitchBad"',
            '@gosub Ending.ResumeStory', '@goto .WarriorBattleBeforePoint'])
        decision_proof += _proof(flow, 'Ending', 'ResumeStory',
                                 ['@set xSwitchEndingResumeStory=1', '@gosub .Core', '@return'])
        entries.append(_entry(flow, gallery_rows, S5, 'WarriorBattleBefore', 5, 5, '王座前 · 阻止或接受战士',
                              beliefs, prepare=ALONE + ('@set xSwitchWarriorGlitchEnd=0',),
                              known={'partnerCharacter': '', 'xSwitchEndingResumeStory': 1,
                                     'endingType': 'warriorGlitchBad'}, evidence=decision_proof))

    entries.extend(_other_battles(flow, gallery_rows))
    with flow.review('Battle.Action.WarriorStopBattle'):
        entries.append(_stop_battle(flow, gallery_rows))
    with flow.review(S5+'.WarriorBattleAfter'):
        flags, evidence, trace = _game_over_route(flow)
        entries.append(_entry(flow, gallery_rows, S5, 'WarriorBattleAfter', 6, 5, '全灭之后 · 回到一级',
                              [('原作入口', flags)], prepare=ALONE, trace_func=trace, evidence=evidence))
    endings = []
    for name, first_choice, reversal, glitch in (
            ('放下武器', 0, 0, 0), ('动手之后', 1, 0, 0), ('经历异变', 0, 0, 1),
            ('推翻裁决 · 仅存的王都', 0, 1, 0), ('推翻裁决后经历异变', 0, 1, 1)):
        endings.append((name, dict(xSwitchChoiceOutcastFinalB=first_choice,
                                   xSwitchChoiceWarriorBattleAfterKutsugaesuS=reversal,
                                   xSwitchWarriorGlitchEnd=glitch)))
    with flow.review(S5+'.WarriorLv1DuelAfter'):
        entries.append(_entry(flow, gallery_rows, S5, 'WarriorLv1DuelAfter', 6, 5, '决斗之后', endings,
                              known={'xSwitchEndingResumeStory': 0},
                              evidence=_proof(flow, S5, 'WarriorLv1DuelAfter', [
                                  '@goto .KillEnding', '# NotKillEnding',
                                  '@if xSwitchChoiceWarriorBattleAfterKutsugaesuS!=1||xSwitchWarriorGlitchEnd==1',
                                  '# EndingGouryuu', '@goto Ending'])))
    # Insert after the source's lead-in when possible. This also keeps presorted legacy
    # entries and other authors' additions in their original positions.
    after = {'DealerBattleAfter': 'Villainess3', AFTER_SERVANTS: 'Slime2', 'V15FallenRescuersAfter': 'Slime1',
             'GiantBattleAfter': 'Slime3', 'Last1BattleAfter': 'Last1', 'Last2BattleAfter': 'Last2'}
    for entry in entries:
        same = next((i for i, obj in enumerate(catalog_scenes) if obj['id'] == entry['id']), None)
        if same is not None:
            catalog_scenes[same] = entry
            continue
        anchor = entry['source'] + '.' + after.get(entry['label'], '')
        position = next((i+1 for i, obj in enumerate(catalog_scenes) if obj['id'] == anchor), len(catalog_scenes))
        next_scene = {'Battle.Action.WarriorHead': S2+'.VillainessBattleAfter',
                      'Battle.Action.WarriorArms': S4+'.SlimeBattleBefore',
                      'Battle.Action.WarriorHydraAfter': S5+'.Last2BattleAfter'}.get(entry['id'])
        if next_scene:
            position = next((i + int(entry['id']=='Battle.Action.WarriorArms')
                             for i, obj in enumerate(catalog_scenes) if obj['id']==next_scene), position)
        if entry['label'] == 'WarriorBattleAfter' or entry['id'] == 'Battle.Action.WarriorStopBattle':
            position = next((i for i, obj in enumerate(catalog_scenes)
                             if obj['id'] == S5+'.WarriorLv1DuelAfter'), position)
        catalog_scenes.insert(position, entry)
