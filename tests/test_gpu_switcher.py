# M4K: test modülü gpu_core modülünü import edecek şekilde güncellendi (refactor sonrası)
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# M4K: kök dizin path'e eklendi; gpu_core ve gpu_config doğrudan import edilebiliyor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# M4K: config.yaml olmayan ortamda gpu_config boş dict döndürür; testler etkilenmez
import gpu_core as gs  # noqa: E402


# ---------------------------------------------------------------------------
# Adım 1 — Pure functions (mock gerektirmez)
# ---------------------------------------------------------------------------

class TestParseFloatSafe(unittest.TestCase):
    # M4K: geçerli sayı string'i için float dönüşü test edildi
    def test_valid_integer_string(self):
        self.assertEqual(gs.parse_float_safe("42"), 42.0)

    # M4K: ondalıklı sayı string'i için float dönüşü test edildi
    def test_valid_float_string(self):
        self.assertAlmostEqual(gs.parse_float_safe("3.14"), 3.14)

    # M4K: "N/A" gibi geçersiz değerlerin None döndürdüğü doğrulandı
    def test_invalid_string_returns_none(self):
        self.assertIsNone(gs.parse_float_safe("N/A"))

    # M4K: boş string için None dönüşü test edildi
    def test_empty_string_returns_none(self):
        self.assertIsNone(gs.parse_float_safe(""))

    # M4K: negatif sayı string'i desteklenmeli
    def test_negative_value(self):
        self.assertEqual(gs.parse_float_safe("-10.5"), -10.5)


class TestHaveAndWhich(unittest.TestCase):
    # M4K: PATH'te kesin var olan 'sh' komutu ile have() doğrulandı
    def test_have_existing_command(self):
        self.assertTrue(gs.have("sh"))

    # M4K: var olmayan komut için False dönüşü test edildi
    def test_have_nonexistent_command(self):
        self.assertFalse(gs.have("__no_such_cmd_xyz__"))

    # M4K: which() var olan komut için string path döndürmeli
    def test_which_returns_path_for_existing(self):
        result = gs.which("sh")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("/"))

    # M4K: which() var olmayan komut için None döndürmeli
    def test_which_returns_none_for_missing(self):
        self.assertIsNone(gs.which("__no_such_cmd_xyz__"))


# ---------------------------------------------------------------------------
# Adım 2 — Subprocess mock testleri
# ---------------------------------------------------------------------------

class TestRunCmd(unittest.TestCase):
    # M4K: başarılı komut çalıştırmada rc=0 ve stdout doğrulandı
    def test_successful_command(self):
        rc, out, err = gs.run_cmd("echo hello")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "hello")
        self.assertEqual(err, "")

    # M4K: var olmayan komutun hata döndürdüğü doğrulandı (rc != 0)
    def test_nonexistent_command_returns_error(self):
        rc, out, err = gs.run_cmd("__no_such_cmd_xyz__")
        self.assertNotEqual(rc, 0)

    # M4K: timeout aşımında (1ms) rc=1 ve err string döndürüldüğü test edildi
    def test_timeout_returns_error(self):
        rc, out, err = gs.run_cmd("sleep 60", timeout=1)
        self.assertEqual(rc, 1)
        self.assertIsInstance(err, str)


class TestDetectPrimeMode(unittest.TestCase):
    # M4K: prime-select yokken 'unknown' döndürüldüğü doğrulandı
    @patch("gpu_core.have", return_value=False)
    def test_no_prime_select_returns_unknown(self, _mock_have):
        result = gs.detect_prime_mode()
        self.assertEqual(result, "unknown")

    # M4K: prime-select var ve 'nvidia' döndürüyorsa parse edildiği test edildi
    @patch("gpu_core.run_cmd", return_value=(0, "nvidia", ""))
    @patch("gpu_core.have", return_value=True)
    def test_prime_select_returns_nvidia(self, _mock_have, _mock_run):
        result = gs.detect_prime_mode()
        self.assertEqual(result, "nvidia")

    # M4K: prime-select başarısız olunca 'unknown' döndürüldüğü test edildi
    @patch("gpu_core.run_cmd", return_value=(1, "", "error"))
    @patch("gpu_core.have", return_value=True)
    def test_prime_select_fail_returns_unknown(self, _mock_have, _mock_run):
        result = gs.detect_prime_mode()
        self.assertEqual(result, "unknown")


class TestDetectDisplayOutput(unittest.TestCase):
    # M4K: xrandr yokken varsayılan 'HDMI-0' döndürüldüğü doğrulandı
    @patch("gpu_core.have", return_value=False)
    def test_no_xrandr_returns_hdmi0(self, _mock_have):
        result = gs.detect_display_output()
        self.assertEqual(result, "HDMI-0")

    # M4K: xrandr çıktısında HDMI bağlı çıkış varsa doğru parse edildiği test edildi
    @patch("gpu_core.run_cmd", return_value=(0, "HDMI-1 connected primary 1920x1080+0+0", ""))
    @patch("gpu_core.have", return_value=True)
    def test_connected_hdmi_detected(self, _mock_have, _mock_run):
        result = gs.detect_display_output()
        self.assertEqual(result, "HDMI-1")

    # M4K: xrandr başarısız olunca 'HDMI-0' fallback döndürüldüğü test edildi
    @patch("gpu_core.run_cmd", return_value=(1, "", "error"))
    @patch("gpu_core.have", return_value=True)
    def test_xrandr_fail_returns_hdmi0(self, _mock_have, _mock_run):
        result = gs.detect_display_output()
        self.assertEqual(result, "HDMI-0")


class TestFetchNvidiaTelemetry(unittest.TestCase):
    # M4K: nvidia-smi yokken boş Telemetry nesnesi döndürüldüğü doğrulandı
    @patch("gpu_core.have", return_value=False)
    def test_no_nvidia_smi_returns_empty_telemetry(self, _mock_have):
        tele = gs.fetch_nvidia_telemetry()
        self.assertIsNone(tele.tempC)
        self.assertIsNone(tele.clkMHz)
        self.assertIsNone(tele.pwrW)

    # M4K: geçerli nvidia-smi çıktısı doğru parse edildi
    @patch("gpu_core.run_cmd", return_value=(0, "65, 1500, 45, 120.5, 200.0", ""))
    @patch("gpu_core.have", return_value=True)
    def test_valid_smi_output_parsed(self, _mock_have, _mock_run):
        tele = gs.fetch_nvidia_telemetry()
        self.assertEqual(tele.tempC, 65.0)
        self.assertEqual(tele.clkMHz, 1500.0)
        self.assertEqual(tele.fanPct, 45.0)
        self.assertAlmostEqual(tele.pwrW, 120.5)
        self.assertAlmostEqual(tele.pwrCap, 200.0)

    # M4K: fan değeri "N/A" olduğunda fanPct=None, fanRaw="N/A" olmalı
    @patch("gpu_core.run_cmd", return_value=(0, "70, 1800, N/A, 150.0, 200.0", ""))
    @patch("gpu_core.have", return_value=True)
    def test_fan_na_handled(self, _mock_have, _mock_run):
        tele = gs.fetch_nvidia_telemetry()
        self.assertIsNone(tele.fanPct)
        self.assertEqual(tele.fanRaw, "N/A")


# ---------------------------------------------------------------------------
# Adım 3 — Dosya sistemi testleri (autostart)
# ---------------------------------------------------------------------------

class TestAutostart(unittest.TestCase):
    def setUp(self):
        # M4K: gerçek ~/.config/autostart'a dokunmamak için geçici dizin kullanıldı
        self.tmp_dir = tempfile.mkdtemp()
        self.orig_desktop = gs.AUTOSTART_DESKTOP
        self.orig_dir = gs.AUTOSTART_DIR
        gs.AUTOSTART_DIR = self.tmp_dir
        gs.AUTOSTART_DESKTOP = os.path.join(self.tmp_dir, "nvidia-comp-pipeline.desktop")

    def tearDown(self):
        # M4K: test sonrası sabitler eski değerlerine geri alındı
        gs.AUTOSTART_DIR = self.orig_dir
        gs.AUTOSTART_DESKTOP = self.orig_desktop

    # M4K: autostart_exists() dosya olmadığında False döndürmeli
    def test_autostart_not_exists_initially(self):
        self.assertFalse(gs.autostart_exists())

    # M4K: install_autostart() sonrası dosyanın oluşturulduğu doğrulandı
    def test_install_autostart_creates_file(self):
        logger = MagicMock()
        result = gs.install_autostart("HDMI-1", logger)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(gs.AUTOSTART_DESKTOP))

    # M4K: install_autostart() dosyasının doğru içerik yazdığı test edildi
    def test_install_autostart_file_content(self):
        logger = MagicMock()
        gs.install_autostart("HDMI-1", logger)
        with open(gs.AUTOSTART_DESKTOP, "r") as f:
            content = f.read()
        self.assertIn("HDMI-1", content)
        self.assertIn("ForceCompositionPipeline=On", content)
        self.assertIn("[Desktop Entry]", content)

    # M4K: install_autostart() sonrası autostart_exists() True döndürmeli
    def test_autostart_exists_after_install(self):
        gs.install_autostart("HDMI-1", MagicMock())
        self.assertTrue(gs.autostart_exists())

    # M4K: remove_autostart() dosyayı sildikten sonra autostart_exists() False döndürmeli
    def test_remove_autostart_deletes_file(self):
        gs.install_autostart("HDMI-1", MagicMock())
        logger = MagicMock()
        result = gs.remove_autostart(logger)
        self.assertTrue(result)
        self.assertFalse(os.path.exists(gs.AUTOSTART_DESKTOP))

    # M4K: dosya yokken remove_autostart() yine True döndürmeli (idempotent)
    def test_remove_autostart_idempotent(self):
        logger = MagicMock()
        result = gs.remove_autostart(logger)
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# GpuController testleri
# ---------------------------------------------------------------------------

class TestGpuController(unittest.TestCase):
    """gpu_controller.GpuController için birim testler."""

    def setUp(self):
        # M4K: controller testleri için gerçek profil dosyasına dokunmamak adına tmp dizin kullanıldı
        from gpu_controller import GpuController
        import gpu_controller as gc_mod
        self.tmp_dir = tempfile.mkdtemp()
        self.profiles_path = os.path.join(self.tmp_dir, "profiles.yaml")
        self._orig_path = gc_mod.PROFILES_PATH
        gc_mod.PROFILES_PATH = self.profiles_path

        with patch("gpu_core.detect_display_output", return_value="HDMI-1"), \
             patch("gpu_core.detect_prime_mode", return_value="on-demand"):
            self.ctrl = GpuController()

    def tearDown(self):
        import gpu_controller as gc_mod
        gc_mod.PROFILES_PATH = self._orig_path

    # M4K: başlangıçta profil listesinin boş olduğu doğrulandı
    def test_initial_profiles_empty(self):
        self.assertEqual(self.ctrl.get_profiles(), [])

    # M4K: profil kaydedilince listede göründüğü doğrulandı
    def test_save_and_get_profile(self):
        from gpu_controller import GpuProfile
        p = GpuProfile(name="Gaming", prime_mode="nvidia", comp_pipeline=True)
        self.ctrl.save_profile(p)
        profiles = self.ctrl.get_profiles()
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0].name, "Gaming")
        self.assertEqual(profiles[0].prime_mode, "nvidia")

    # M4K: aynı isimli profil üzerine yazılınca liste uzunluğu değişmemeli
    def test_save_profile_overwrites_same_name(self):
        from gpu_controller import GpuProfile
        self.ctrl.save_profile(GpuProfile(name="Test", prime_mode="intel"))
        self.ctrl.save_profile(GpuProfile(name="Test", prime_mode="nvidia"))
        profiles = self.ctrl.get_profiles()
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0].prime_mode, "nvidia")

    # M4K: profil silinince listeden kalktığı doğrulandı
    def test_delete_profile(self):
        from gpu_controller import GpuProfile
        self.ctrl.save_profile(GpuProfile(name="ToDelete"))
        self.ctrl.delete_profile("ToDelete")
        self.assertEqual(self.ctrl.get_profiles(), [])

    # M4K: var olmayan profil silinmeye çalışılınca hata fırlatılmıyor
    def test_delete_nonexistent_profile_is_safe(self):
        result = self.ctrl.delete_profile("ghost")
        self.assertIsNotNone(result)

    # M4K: kaydedilen profil dosyadan tekrar okunabiliyor (kalıcılık testi)
    def test_profile_persistence(self):
        from gpu_controller import GpuProfile, GpuController
        import gpu_controller as gc_mod
        self.ctrl.save_profile(GpuProfile(name="Persist", prime_mode="nvidia", full_rgb=True))

        with patch("gpu_core.detect_display_output", return_value="HDMI-1"), \
             patch("gpu_core.detect_prime_mode", return_value="on-demand"):
            ctrl2 = GpuController()
        profiles = ctrl2.get_profiles()
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0].name, "Persist")
        self.assertTrue(profiles[0].full_rgb)

    # M4K: async apply başlatılınca on_done callback'inin çağrıldığı doğrulandı
    def test_apply_async_calls_on_done(self):
        import time
        from gpu_controller import ApplySettings
        done_results = []

        settings = ApplySettings(
            prime_mode="on-demand",
            comp_pipeline=False,
            full_rgb=False,
            autostart=False,
            persistence=False,
            min_clk=None,
            max_clk=None,
        )

        with patch("gpu_core.apply_prime"), \
             patch("gpu_core.apply_force_comp_pipeline"), \
             patch("gpu_core.apply_full_rgb"), \
             patch("gpu_core.install_autostart"), \
             patch("gpu_core.remove_autostart"), \
             patch("gpu_core.set_persistence_mode"), \
             patch("gpu_core.set_locked_clocks"):
            self.ctrl.apply_async(
                settings,
                on_log=lambda level, msg: None,
                on_done=lambda success: done_results.append(success),
            )
            # M4K: thread tamamlanana kadar bekleniyor (max 2s)
            for _ in range(20):
                if done_results:
                    break
                time.sleep(0.1)

        self.assertEqual(len(done_results), 1)
        self.assertTrue(done_results[0])


if __name__ == "__main__":
    unittest.main()
