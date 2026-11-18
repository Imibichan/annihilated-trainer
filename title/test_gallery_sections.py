import unittest

from catalog_ui import category_sections


class GallerySectionTests(unittest.TestCase):
    def test_main_chapters_and_guest_appearances_have_separate_pages(self):
        def scene(i, group, chapter, **fields):
            return dict(id=str(i), group=group, chapter=chapter, **fields)
        mage = [scene(i, "Mage", 1) for i in range(11)]
        cross = scene("guest", "Hero", 3, alsoGroups=["Mage"])
        scenes = [cross, *mage, scene("end", "Mage", 6), scene("extra", "Mage", 7)]
        sections = category_sections(scenes, "Mage")
        self.assertEqual([(s.caption, [len(p) for p in s.pages]) for s in sections],
                         [("第1层", [10, 1]), ("终章", [1]), ("独立画稿", [1]), ("其他路线登场", [1])])
        self.assertEqual(sections[0].pages[0] + sections[0].pages[1], mage)
        self.assertEqual(sections[-1].pages[0], [cross])
        self.assertEqual(category_sections(scenes, "Priest"), [])

    def test_conditional_and_trial_entries_never_share_a_chapter_with_unplaced_art(self):
        kinds = ["unplaced", "trial", "random", "conditional"]
        scenes = [dict(group="Shared", chapter=7, sequenceKind=k) for k in kinds]
        self.assertEqual([s.caption for s in category_sections(scenes, "Shared")],
                         ["条件事件", "迷宫随机事件", "试玩结尾", "独立画稿"])
