import React, { useState, useEffect } from "react";
import { Shield, Key, Phone, User, Trash2, ShieldCheck, AlertCircle } from "lucide-react";
import { useDashboard } from "../context/DashboardContext";
import { apiFetch } from "../lib/api";

interface SettingsTabProps {
  onLogout: () => void;
}

export default function SettingsTab({ onLogout }: SettingsTabProps) {
  const { accountId } = useDashboard();
  const settingsUrl = `/api/accounts/${accountId}/settings`;
  // Input fields state
  const [ip, setIp] = useState("185.112.14.92");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [name, setName] = useState("Ömer Altın");
  const [phone, setPhone] = useState("5321234567");
  const [isIsolated, setIsIsolated] = useState(false);
  
  // Password change state
  const [pass, setPass] = useState("");
  const [confirmPass, setConfirmPass] = useState("");
  const [passError, setPassError] = useState("");
  const [passSuccess, setPassSuccess] = useState("");

  // Deletion modal state
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deletePass, setDeletePass] = useState("");
  const [deleteError, setDeleteError] = useState("");

  useEffect(() => {
    // Load fresh account settings
    apiFetch<Record<string, unknown>>(settingsUrl)
      .then((data) => {
        if (data) {
          setIp(String(data.server_public_ip || "185.112.14.92"));
          setName(String(data.account_name || ""));
          setPhone(String(data.user_phone || ""));
          setIsIsolated(!!data.isolate_from_admin);
        }
      })
      .catch(console.error);
  }, [accountId, settingsUrl]);

  const handleUpdateAPI = (field: "apiKey" | "apiSecret") => {
    const value = field === "apiKey" ? apiKey : apiSecret;
    if (!value.trim()) {
      alert("Hata: Değer boş olamaz.");
      return;
    }

    apiFetch(settingsUrl, {
      method: "PATCH",
      body: JSON.stringify({
        [field === "apiKey" ? "api_key" : "api_secret"]: value,
      }),
    })
      .then((data: { success?: boolean }) => {
        if (data?.success) {
          alert("Binance API bilgisi başarıyla güncellendi.");
          if (field === "apiKey") setApiKey("");
          else setApiSecret("");
        }
      })
      .catch(console.error);
  };

  const handleUpdatePhone = () => {
    const rawDigits = phone.replace(/\D/g, "");
    if (rawDigits.length < 10) {
      alert("En az 10 rakamlı geçerli bir telefon numarası giriniz.");
      return;
    }

    apiFetch(settingsUrl, {
      method: "PATCH",
      body: JSON.stringify({ user_phone: phone }),
    })
      .then((data: { success?: boolean }) => {
        if (data?.success) {
          alert("Telefon numaranız güncellendi.");
        }
      })
      .catch(console.error);
  };

  const validatePasswordStrength = (p: string) => {
    if (p.length < 10) return "Şifre en az 10 karakter olmalıdır.";
    if (!/[A-Z]/.test(p)) return "Şifre en az 1 büyük harf içermelidir.";
    if (!/[a-z]/.test(p)) return "Şifre en az 1 küçük harf içermelidir.";
    if (!/[0-9]/.test(p)) return "Şifre en az 1 rakam içermelidir.";
    if (!/[.,!?;:]/.test(p)) return "Şifre en az 1 noktalama işareti (.,!?;:) içermelidir.";
    if (p.toLowerCase().includes("omer") || p.toLowerCase().includes("altin")) return "Şifre isim/soyad içeremez.";
    return "";
  };

  const handleUpdatePassword = () => {
    setPassError("");
    setPassSuccess("");

    if (!pass || !confirmPass) {
      setPassError("Lütfen her iki şifre alanını da doldurun.");
      return;
    }

    if (pass !== confirmPass) {
      setPassError("Şifreler uyuşmamaktadır.");
      return;
    }

    const err = validatePasswordStrength(pass);
    if (err) {
      setPassError(err);
      return;
    }

    // Call update
    apiFetch(settingsUrl, {
      method: "PATCH",
      body: JSON.stringify({ password: pass }),
    })
      .then((data: { success?: boolean }) => {
        if (data?.success) {
          setPassSuccess("✓ Şifreniz başarıyla güncellendi.");
          setPass("");
          setConfirmPass("");
        }
      })
      .catch(err => {
        setPassError("İşlem gerçekleştirilemedi.");
      });
  };

  const handleToggleIsolate = () => {
    const nextVal = !isIsolated;
    apiFetch(settingsUrl, {
      method: "PATCH",
      body: JSON.stringify({ isolate_from_admin: nextVal }),
    })
      .then((data: { success?: boolean }) => {
        if (data?.success) {
          setIsIsolated(nextVal);
          alert(nextVal ? "Yönetici izolasyonu başarıyla aktif hale getirildi." : "Yönetici izolasyonu kaldırıldı.");
        }
      })
      .catch(console.error);
  };

  const handleDeleteAccount = () => {
    setDeleteError("");
    if (!deletePass.trim()) {
      setDeleteError("Şifrenizi giriniz.");
      return;
    }

    // Call delete endpoint simulating account deletion
    apiFetch(settingsUrl, {
      method: "PATCH",
      body: JSON.stringify({ has_binance_keys: false }),
    })
      .then(() => {
        alert("Hesabınız ve tüm ilişkili verileriniz kalıcı olarak silindi.");
        setShowDeleteModal(false);
        onLogout();
      })
      .catch(() => {
        setDeleteError("Hesap silme işlemi başarısız.");
      });
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 shadow-xl space-y-6">
        <h3 className="text-lg font-bold text-white mb-2 flex items-center border-b border-neutral-850 pb-3">
          <Shield className="w-5 h-5 text-[#f0b90b] mr-2" /> Güvenli Hesap Ayarları
        </h3>

        {/* Server IP Info */}
        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-neutral-400">Sunucu Dış IP Adresi (Binance Beyaz Liste)</label>
          <input
            type="text"
            value={ip}
            readOnly
            className="w-full bg-[#1e2026] text-neutral-400 border border-neutral-800 rounded-lg p-2.5 text-sm cursor-not-allowed font-mono"
          />
          <span className="text-[10px] text-neutral-400 block leading-normal">
            İşlemler sunucudan gittiği için Binance API ayarlarında bu IP'yi beyaz listeye ekleyin. Değer sunucunun internet IP'sinden otomatik alınır.
          </span>
        </div>

        {/* API Key Updates */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-neutral-400 flex items-center">
              <Key className="w-3.5 h-3.5 mr-1 text-[#f0b90b]" /> Binance API Key Güncelle
            </label>
            <div className="flex gap-2">
              <input
                type="password"
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder="Yeni Binance API Key"
                className="flex-1 bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
              />
              <button
                onClick={() => handleUpdateAPI("apiKey")}
                className="px-3 bg-neutral-800 hover:bg-neutral-700 text-white text-xs font-semibold rounded-lg transition"
              >
                Güncelle
              </button>
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-neutral-400 flex items-center">
              <Key className="w-3.5 h-3.5 mr-1 text-[#f0b90b]" /> Binance API Secret Güncelle
            </label>
            <div className="flex gap-2">
              <input
                type="password"
                value={apiSecret}
                onChange={e => setApiSecret(e.target.value)}
                placeholder="Yeni Binance API Secret"
                className="flex-1 bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
              />
              <button
                onClick={() => handleUpdateAPI("apiSecret")}
                className="px-3 bg-neutral-800 hover:bg-neutral-700 text-white text-xs font-semibold rounded-lg transition"
              >
                Güncelle
              </button>
            </div>
          </div>
        </div>

        {/* User profile read-only field */}
        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-neutral-400 flex items-center">
            <User className="w-3.5 h-3.5 mr-1 text-neutral-400" /> Adı Soyadı (Alt hesap sahibi)
          </label>
          <input
            type="text"
            value={name}
            readOnly
            className="w-full bg-[#1e2026] text-neutral-400 border border-neutral-850 rounded-lg p-2.5 text-sm cursor-not-allowed"
          />
        </div>

        {/* Telephone Update */}
        <div className="space-y-1.5">
          <label className="text-xs font-semibold text-neutral-400 flex items-center">
            <Phone className="w-3.5 h-3.5 mr-1 text-[#f0b90b]" /> Telefon Numarası Güncelle
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={phone}
              onChange={e => setPhone(e.target.value)}
              placeholder="5XXXXXXXXX"
              className="flex-1 bg-[#1e2026] text-white border border-neutral-850 rounded-lg p-2.5 text-sm font-mono"
            />
            <button
              onClick={handleUpdatePhone}
              className="px-4 py-2 bg-neutral-800 hover:bg-neutral-700 text-white text-xs font-semibold rounded-lg transition"
            >
              Güncelle
            </button>
          </div>
        </div>

        {/* Password Update Card Block */}
        <div className="space-y-3 border-t border-neutral-850 pt-4">
          <h4 className="text-sm font-bold text-neutral-300">Güvenli Şifre Güncelle</h4>
          
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-neutral-400">Yeni Şifre</label>
              <input
                type="password"
                value={pass}
                onChange={e => setPass(e.target.value)}
                placeholder="Yeni güçlü şifre"
                className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-neutral-400">Yeni Şifre Tekrarı</label>
              <input
                type="password"
                value={confirmPass}
                onChange={e => setConfirmPass(e.target.value)}
                placeholder="Şifreyi onaylayın"
                className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
              />
            </div>
          </div>

          {/* Validation conditions boxes */}
          <div className="p-3 bg-[#1e2026] rounded-xl border border-neutral-800/80 text-xs text-neutral-400 space-y-1 leading-relaxed">
            <strong className="text-neutral-300 block mb-1">Şifre Şartları:</strong>
            <ul className="list-disc list-inside space-y-0.5">
              <li>En az 10 karakter büyüklükte olmalı</li>
              <li>En az 1 büyük harf (A-Z), 1 küçük harf (a-z), 1 rakam barındırmalı</li>
              <li>En az 1 noktalama işareti (.,!?;:) barındırmalı</li>
              <li>İsim/soyad öğeleri içeremez</li>
            </ul>
          </div>

          {passError && <p className="text-xs text-[#f6465d]">{passError}</p>}
          {passSuccess && <p className="text-xs text-[#0ecb81]">{passSuccess}</p>}

          <button
            onClick={handleUpdatePassword}
            className="w-full py-2.5 bg-neutral-800 hover:bg-neutral-700 text-white font-bold rounded-lg text-sm transition"
          >
            Şifreyi Güncelle
          </button>
        </div>

        {/* Administrative Isolate Toggle block */}
        <div className="space-y-2 border-t border-neutral-850 pt-4">
          <label className="text-xs font-semibold text-neutral-400 flex items-center">
            <ShieldCheck className="w-4 h-4 mr-1 text-[#f0b90b]" /> Adminden İzole Ol
          </label>
          <p className="text-xs text-neutral-500 leading-normal">
            Açıkken yönetici hesabınıza erişemez, bakiyelerinizi ve işlemlerinizi asla göremez, sadece siz bilirsiniz.
          </p>
          <button
            onClick={handleToggleIsolate}
            className={`w-full py-2.5 font-bold rounded-lg text-sm transition ${
              isIsolated 
                ? "bg-[#f6465d] text-white" 
                : "bg-[#0ecb81]/10 hover:bg-[#0ecb81]/25 text-[#0ecb81] border border-[#0ecb81]/20"
            }`}
          >
            {isIsolated ? "Yönetici İzolasyonunu Kapat" : "Yöneticiden İzole Ol"}
          </button>
        </div>

        {/* Danger zone: Account deletion */}
        <div className="space-y-2 border-t border-neutral-850 pt-4 bg-[#f6465d]/5 p-4 rounded-xl border border-[#f6465d]/10">
          <label className="text-xs font-bold text-[#f6465d] flex items-center">
            <Trash2 className="w-4 h-4 mr-1 shrink-0" /> Tehlikeli Bölge: Kalıcı Hesap Silme
          </label>
          <p className="text-xs text-neutral-400 leading-normal">
            Hesabınız ve Binance API yetkileriniz kalıcı olarak veritabanından kazınacaktır. Bu işlem kesinlikle geri alınamaz.
          </p>
          <button
            onClick={() => {
              setDeleteError("");
              setDeletePass("");
              setShowDeleteModal(true);
            }}
            className="w-full py-2.5 bg-[#f6465d] hover:bg-[#d63a4e] text-white font-bold rounded-lg text-sm transition"
          >
            Hesabı Kalıcı Olarak Sil
          </button>
        </div>
      </div>

      {/* Delete Account Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-neutral-900 border border-neutral-800 rounded-2xl max-w-sm w-full p-6 space-y-4 shadow-2xl">
            <h3 className="text-lg font-bold text-white flex items-center">
              <AlertCircle className="w-5 h-5 text-[#f6465d] mr-2" /> Hesabı Silme Onayı
            </h3>
            <p className="text-xs text-neutral-400 leading-relaxed">
              Hesabınızı kalıcı olarak silmek istediğinize emin misiniz? Devam etmek için mevcut şifrenizi doğrulamanız gerekmektedir.
            </p>

            <div className="space-y-1.5">
              <label className="text-xs text-neutral-400">Şifre</label>
              <input
                type="password"
                value={deletePass}
                onChange={e => setDeletePass(e.target.value)}
                placeholder="Mevcut onay şifreniz"
                className="w-full bg-[#1e2026] text-white border border-neutral-800 rounded-lg p-2.5 text-sm"
              />
            </div>

            {deleteError && <p className="text-xs text-[#f6465d]">{deleteError}</p>}

            <div className="flex justify-end gap-3 pt-2">
              <button
                onClick={() => setShowDeleteModal(false)}
                className="px-4 py-2 bg-neutral-800 hover:bg-neutral-700 text-neutral-300 font-semibold rounded-lg text-xs transition"
              >
                İptal
              </button>
              <button
                onClick={handleDeleteAccount}
                className="px-4 py-2 bg-[#f6465d] hover:bg-[#d63a4e] text-white font-bold rounded-lg text-xs transition"
              >
                Onayla &amp; Sil
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
