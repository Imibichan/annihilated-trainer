"""Native command signatures used by the private replay compiler."""

# Pure stock commands supply defaults specific to this game build. Literal values
# and playback locations are replaced below. No custom game assembly is needed.
TEMPLATES = {
    "goto": ("Scenario_Mage2", r"@goto [\w.]+"),
    "gosub": ("Scenario_Mage2", r"@gosub [\w.]+"),
    "set": ("Scenario_Mage2", r'@set \w+="\w+"'),
    "storeEnemyNextActionSet": ("Battle", r'@storeEnemyNextActionSet enemyId:\{yValWarriorFinalSlot\} actionSetName:"warriorFinalBerserkStrength"'),
    "choice": ("Scenario_Mage2", r'@choice "[^"{}]+" goto:[\w.]+'),
    "stop": ("Scenario_Mage2", r"@stop"),
    "hidePrinter": ("Scenario_Mage2", r"@hidePrinter"),
    "wait": ("Battle", r"@wait i"),
    "hideUI": ("Battle", r"@hideUI \w+"),
    "clearChoice": ("Action", r"@clearChoice \*"),
    "title": ("Dungeon", r"@title"),
    "save": ("Dungeon", r"@save"),
    "back": ("Opening", r'@back "none"'),
}
