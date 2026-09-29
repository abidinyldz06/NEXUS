from __future__ import annotations

import unittest

from nexus.hub.routing import RouteAdviceError, advise


CASES = [
    ("Geçen konuşmada aldığımız kararı bul", "memory_search", "NEXUS"),
    ("Obsidian notlarında vize kararını ara", "memory_search", "NEXUS"),
    ("Vault içinde eski notu göster", "memory_search", "NEXUS"),
    ("Son sohbetimizde karar neydi?", "memory_search", "NEXUS"),
    ("NEXUS hafızasında randevu notunu bul", "memory_search", "NEXUS"),
    ("Önceki konuşmayı hatırla", "memory_search", "NEXUS"),
    ("Yarın saat 9'da bana hatırlat", "reminder", "Hermes"),
    ("Faturayı cuma günü anımsat", "reminder", "Hermes"),
    ("Toplantı için alarm kur", "reminder", "Hermes"),
    ("İlaç saatini bildir", "reminder", "Hermes"),
    ("Yarın sabah aramamı hatırlat", "reminder", "Hermes"),
    ("Şu konuyu araştırılacak görev olarak ekle", "task_draft", "Hermes"),
    ("Yeni görev taslağı oluştur", "task_draft", "Hermes"),
    ("Kaynakları araştır", "task_draft", "Hermes"),
    ("Bu projeyi planla", "task_draft", "Hermes"),
    ("Rakipleri araştır", "task_draft", "Hermes"),
    ("GitHub PR #53 durumunu göster", "status_lookup", "GitHub"),
    ("GitHub reposunun durumuna bak", "status_lookup", "GitHub"),
    ("Pull request 53 durumunu kontrol et", "status_lookup", "GitHub"),
    ("GitHub PR #45 listesini göster", "status_lookup", "GitHub"),
    ("Seçtiğim metni özetle", "summary", "Hermes"),
    ("Bu paragrafı kısalt", "summary", "Hermes"),
    ("Şu belgeyi kısa anlat", "summary", "Hermes"),
    ("Metni özetle", "summary", "Hermes"),
    ("GitHub PR #53 merge et", "external_action", "GitHub"),
    ("Vault notlarını sil", "external_action", None),
    ("API anahtarını gönder", "external_action", None),
    ("Bu dosyayı Google Drive'a yükle", "external_action", None),
    ("Ödemeyi yap", "external_action", None),
    ("Merhaba", "unclear", None),
]


class RoutingTests(unittest.TestCase):
    def test_fixed_thirty_examples(self) -> None:
        self.assertEqual(30, len(CASES))
        correct = 0
        for request, intent, target in CASES:
            with self.subTest(request=request):
                result = advise(request)
                correct += result["intent"] == intent and result["target_app"] == target
                self.assertFalse(result["execution_enabled"])
                self.assertNotIn(request, result.values())
        self.assertGreaterEqual(correct, 27)

    def test_external_and_sensitive_requests_never_enable_work(self) -> None:
        for request, _, _ in CASES[24:29]:
            with self.subTest(request=request):
                result = advise(request)
                self.assertEqual("requires_review", result["status"])
                self.assertIsNone(result["model_role"])
                self.assertFalse(result["execution_enabled"])
        sensitive = advise("Seçtiğim metni özetle", data_class="sensitive")
        self.assertEqual("requires_review", sensitive["status"])
        self.assertIsNone(sensitive["target_app"])
        self.assertIsNone(sensitive["model_role"])
        self.assertFalse(sensitive["execution_enabled"])

    def test_local_only_never_selects_external_model_role(self) -> None:
        result = advise("Seçtiğim metni özetle", data_class="local_only")
        self.assertEqual("local_required", result["model_role"])
        self.assertFalse(result["execution_enabled"])

    def test_ambiguous_and_invalid_requests_fail_closed(self) -> None:
        mixed = advise("Hafızada kararı bul ve metni özetle")
        self.assertEqual("needs_clarification", mixed["status"])
        self.assertIsNone(mixed["target_app"])
        for text in ("", " " * 2, "x" * 501):
            with self.subTest(text=text[:8]):
                with self.assertRaises(RouteAdviceError):
                    advise(text)
        with self.assertRaises(RouteAdviceError):
            advise("Metni özetle", data_class="invalid")
        with self.assertRaises(RouteAdviceError):
            advise("Metni özetle", data_class=["local_only"])  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
