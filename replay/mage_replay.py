"""Mage encounters that span map callbacks, battle actions and endings."""


def _dropout_setup(flags, enemy):
    from scenes import _setup

    return _setup('Mage', 3, 4, flags, '') + [
        '@gosub Func.ShowSettings', '@set xSwitchBoss3BattleEvent=0', '@set battleTarget="dropout"',
        f'@set addEnemyResourceNames="{enemy}"', '@set showEnemyUI=false',
    ]


def _charged_attack(flow, gallery_rows):
    from scenes import _battle_action

    proof = [
        ('Battle', '@gosub .DropoutMageChargeModeBranch if:battleTarget=="dropout"&&enemy1Death<=0&&xSwitchDropoutForm2EventStarted!=1&&(GetEnemyNextActionSetName(1)=="dropoutGrandAttackVsMage"||GetEnemyNextActionSetName(1)=="dropoutGrandAttack")'),
        ('Battle', '@gosub .DropoutBigMagicBreakBranch if:battleTarget=="dropout"&&partnerCharacter=="mage"&&enemy{tempEnemyId}BeforeActionSetName=="dropoutGrandAttackVsMage"'),
        ('Battle', '@gosub .DropoutMageBigMagicBreakBranch'),
    ]
    commands = [
        '@goto Test2.Finish if:xSwitchDropoutMageChargeModeBranchDone==1',
        '@storeEnemyNextActionSet enemyId:1 actionSetName:"dropoutGrandAttackVsMage"',
        '@gosub Battle.DropoutMageChargeModeBranch',
    ]
    presets = []
    for mage_front, title in ((1, '此前由魔法师站在前排'), (0, '此前由主角站在前排')):
        flags = {'xSwitchMageOutcastMageForward':mage_front, 'xSwitchMageOutcastMeForward':1-mage_front}
        setup = _dropout_setup(flags, 'dropout')
        scene = _battle_action(flow, gallery_rows, 'Battle.Action.DropoutMageCharge', 'Mage', 3,
                               '挡在你面前的魔法师', setup, commands, ('DropoutMageChargeModeBranch',),
                               proof, '落选者蓄力，魔法师上前承受大魔法；原作按此前的站位播放对白。')
        preset = scene['presets'][0]
        preset['title'] = title
        preset['actionAtFirstCommand'].update(target='Test2.Finish', skipTiming=False)
        presets.append(preset)
        if len(presets) == 1:
            entry = scene
    entry['presets'] = presets
    return entry


def _dropout_rematch(flow, gallery_rows):
    from scenes import _battle_action

    proof = [
        ('Battle', '@gosub .DropoutSecondFormTransitionCore'),
        ('Battle', '@gosub .DropoutMageStealAfterBreakBranch'),
        ('Battle', '@gosub .DropoutMageTransformReactionBranch'),
        ('Action', '@gosub Battle.DropoutStealAfterBreakBranch'),
        ('Action', '@gosub Battle.DropoutSecondFormTransitionCore'),
        ('Action', '@if xSwitchReturnSteal==1'),
    ]
    defeat = ['@set enemy1Health=1;enemy1StateBlock=0;enemy1StateBarrier=0;enemy1StateEvading=0',
              '@set selectCommand=-1;selectionEnemyTargetId="enemy1"']
    with flow.review('Battle.Action.MageDropoutSecondForm'):
        scene = _battle_action(flow, gallery_rows, 'Battle.Action.MageDropoutSecondForm', 'Mage', 3,
                               '落选者 · 放下法杖之后', _dropout_setup({}, 'dropout'), defeat, (), proof,
                               '攻击击倒落选者或在破防后夺杖，继续原作第二形态变身与对白。')
        first = scene['presets'][0]
        first['title'] = '直接击倒第一形态'
        # The native steal routine obtains the weapon, records the theft and
        # dispatches the corresponding dialogue and the complete transformation.
        steal = ['@set actionUserId="player";actionTargetId="enemy1";actionType="stealAttack"',
                 '@set xSwitchDropoutCriticalParryUsed=1', '@set xSwitchReturnSteal=1',
                 '@gosub Action.StealEnemyWeaponFromCurrentTarget']
        scene['presets'].append(dict(first, title='破防后夺取法杖',
                                     actionAtFirstCommand=dict(target='Test2.Finish', commands=steal, skipTiming=False)))
        yield scene

    # Restore the already registered second form and the end of its fourth turn.
    # The native callback revives the mage, animates the surprise hit and runs
    # the remaining conversation before the next playable turn.
    commands = ['@set yValDropoutForm2Slot=1;xSwitchDropoutForm2EventStarted=1;xDropoutForm2RoundCount=4',
                '@set xSwitchDropoutMageTemporarilyDown=1;partnerDeath=1;partnerHealth=0',
                '@gosub Battle.DropoutSurvive4TurnsBranch']
    proof = [('Battle', '@gosub .DropoutSurvive4TurnsBranch'), ('Battle', '@gosub .DropoutMageSurvive4TurnsBranch'),
             ('Battle', '@set enemy{yValDropoutForm2Slot}Health-=partnerDex')]
    with flow.review('Battle.Action.MageDropoutReturn'):
        recovery = _battle_action(flow, gallery_rows, 'Battle.Action.MageDropoutReturn', 'Mage', 3,
                                  '第四回合 · 魔法师归来', _dropout_setup({}, 'dropoutForm2'),
                                  commands, (), proof, '落选者第二形态第四回合的原作救场、反击及对白。')
        recovery['actionAtFirstCommand'].update(target='Test2.Finish', skipTiming=False)
        yield recovery


def integrate(scenes, flow, gallery_rows):
    from scenes import _battle_action, _setup

    routes = {s['id']:s for s in scenes}
    after = next((i for i, s in enumerate(scenes) if s['id'] == 'Scenario_Mage3.DropoutBattleAfter'), len(scenes))
    additions = []
    with flow.review('Battle.Action.DropoutMageCharge'):
        additions.append(_charged_attack(flow, gallery_rows))
    additions.extend(_dropout_rematch(flow, gallery_rows))
    scenes[after:after] = additions
    for label, event in [('WakimitiRoute', 903), ('WakimitiRoute_AfterBattle1', 904),
                         ('WakimitiRoute_AfterBattle2', 905)]:
        with flow.review('Scenario_Mage5.' + label):
            entry = routes['Scenario_Mage5.' + label]
            entry['setupCommands'].extend(['@set xSwitchScenarioMage9TakeWakimiti=1', f'@set eventNum={event}'])

    with flow.review('Scenario_Mage5.WakimitiRoute_AfterBattle2'):
        battle = flow.sources['Battle']
        rescue = routes['Scenario_Mage5.WakimitiRoute_AfterBattle2']
        preset = rescue['presets'][0]
        after_support = battle.text.index('@gosub .PriestFinalPhaseClearText', battle.labels['PriestFinalPhaseTransitionCheck'])
        next_phase = battle.text.index('@gosub .PriestFinalResummonEnemy', after_support)
        counter = '@gosub .PriestFinalMageNotMaryokuForm1CounterText if:xPriestFinalPhase==1'
        if not (after_support < next_phase < battle.labels['PriestFinalResummonEnemy'] and
                counter in battle.text[battle.labels['PriestFinalPhaseClearText']:battle.labels['PriestFinalPlayerDeathTextCheck']]):
            raise ValueError('反派千金救出战士的形态切换条件已变化')
        battle_art = [r['id'] for r in sorted(gallery_rows, key=lambda r:r['line']) if r['source']=='Battle' and
                      ('"CG/villainessAllyCut"' in battle.text[r['line']] or
                       r['label']=='PriestFinalMageNotMaryokuForm1CounterText')]
        if len(battle_art) != 2:
            raise ValueError('反派千金支援与救援的两段原作演出未匹配')
        preset['galleryIds'].extend(battle_art)
        rescue['galleryIds'] = list(preset['galleryIds'])
        preset['exits'] = ['Battle.InitializeCommand', 'Battle.PriestFinalResummonEnemy']
        rescue['exits'] = list(preset['exits'])
        # Run her multi-target support with the full original encounter first. The
        # following normal attack selects the registered boss, leaving every limb in play.
        preset['actionAtFirstCommand'] = dict(target='Battle.PlayerAttack', skipTiming=True, selectBoss=True,
            commands=['@gosub Battle.PriestFinalAfterFormStartSetupText',
                      '@set enemy{xPriestFinalSlot}Health=1;enemy{xPriestFinalSlot}StateBlock=0',
                      '@set enemy{xPriestFinalSlot}StateBarrier=0;enemy{xPriestFinalSlot}StateEvading=0',
                      '@set selectCommand=-1;selectionEnemyTargetId=GetEnemyStr(xPriestFinalSlot)'])

    # In the unkept-promise branch the death handler plays the stabbing scene,
    # returns from Battle, then the original caller enters its corresponding ending.
    with flow.review('Battle.Action.MageBrokenPromise'):
        path = flow.sources['Scenario_Mage5']
        flags = {'xSwitchMageChoiceGetMaryoku':1, 'xSwitchMageChoiceNotMaryoku':0,
                 'xSwitchMageYakusokuSinai':1, 'xSwitchMageYakusokuSita':0}
        setup = _setup('Mage', 8, 2, flags, '') + [
            '@set backgroundName="last"', '@gosub Func.ShowBackground',
            '@set xSwitchBoss5BattleEvent=1', '@set battleTarget="priest"',
            '@set playerStateImmortal=100', '@set playerStateCovering=100',
            '@set playerStr+=82', '@set playerDex+=82', '@set playerAgi+=82', '@set playerMag+=82',
            '@set xSwitchSystemDebugPriestPhase=4', '@gosub Func.ShowSettings',
            '@set addEnemyResourceNames="priest"', '@set showEnemyUI=false',
        ]
        proof = [('Scenario_Mage5','@goto .PriestBattleBadRouteBattleFinaleEnd'),
                 ('Battle','@gosub Scenario_Mage5.PriestBattleBadRouteBattleFinale'),
                 ('Battle','@set xSwitchBattleEndWithoutResultsRequested=1'),
                 ('Scenario_Mage5','@set endingType="mage5YakusokuSinaiBad"')]
        finale = _battle_action(flow, gallery_rows, 'Battle.Action.MageBrokenPromise', 'Mage', 6,
                                '未许下的约定', setup,
                                ['@set enemy1Health=1;enemy1StateBlock=0;enemy1StateBarrier=0;enemy1StateEvading=0',
                                 '@set selectCommand=-1;selectionEnemyTargetId="enemy1"'], (), proof,
                                '从僧侣第四形态的最后一击进入原作败局与尾声。')
        # On this route Dungeon would normally supply the return site after Battle.
        end = 'PriestBattleBadRouteBattleFinaleEnd'
        finale['presets'][0]['finishCommands'] = ['@goto Scenario_Mage5.'+end]
        gallery_ids = [r['id'] for r in gallery_rows if
                       (r['source']=='Scenario_Mage5' and path.labels['PriestBattleBadRouteBattleFinale'] <= r['line'] < path.labels['NotMaryokuRoute'])
                       or (r['source']=='Ending' and r['label']=='mage5YakusokuSinaiBad')]
        finale['galleryIds'] = finale['presets'][0]['galleryIds'] = gallery_ids
        scenes.append(finale)
