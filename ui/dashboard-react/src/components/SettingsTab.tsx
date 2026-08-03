import React, { useState, useEffect } from "react";
import { Shield, Key, Phone, User, Trash2, ShieldCheck, AlertCircle } from "lucide-react";
import { useDashboard } from "../context/DashboardContext";
import { apiFetch } from "../lib/api";
import PushNotificationSettings from "../features/notifications/PushNotificationSettings";

interface SettingsTabProps {
  onLogout: () => void;
}

interface SettingsSnapshot {
  ip: string;
  name: string;
  phone: string;
  isIsolated: boolean;
}

const settingsCache = new Map<number, SettingsSnapshot>();

export default function SettingsTab({ onLogout }: SettingsTabProps) {
  const { accountId } = useDashboard();
  const settingsUrl = `/api/accounts/${accountId}/settings`;
  // Input fields state
  const cached = settingsCache.get(accountId);
  const [ip, setIp] = useState(cached?.ip || "—");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [name, setName] = useState(cached?.name || "");
  const [phone, setPhone] = useState(cached?.phone || "");
  const [isIsolated, setIsIsolated] = useState(cached?.isIsolated || false);
  const [actionMessage, setActionMessage] = useState("");
  const [actionError, setActionError] = useState("");
  const [activeAction, setActiveAction] = useState("");
  
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
    const saved = settingsCache.get(accountId);
    if (saved) {
      setIp(saved.ip);
      setName(saved.name);
      setPhone(saved.phone);
      setIsIsolated(saved.isIsolated);
      return;
    }
    apiFetch<Record<string, unknown>>(settingsUrl)
      .then((data) => {
        if (data) {
          const snapshot = {
            ip: String(data.server_public_ip || "—"),
            name: String(data.account_name || ""),
            phone: String(data.user_phone || ""),
            isIsolated: !!data.isolate_from_admin,
          };
          settingsCache.set(accountId, snapshot);
          setIp(snapshot.ip);
          setName(snapshot.name);
          setPhone(snapshot.phone);
          setIsIsolated(snapshot.isIsolated);
        }
      })
      .catch(console.error);
  }, [accountId, settingsUrl]);

  const handleUpdateAPI = async (field: "apiKey" | "apiSecret") => {
    const value = field === "apiKey" ? apiKey : apiSecret;
    if (!value.trim()) {
      setActionError("Değer boş olamaz.");
      return;
    }
    setActiveAction(field);
    setActionError("");
    setActionMessage("");
    try {
      const data = await apiFetch<{ ok?: boolean; message?: string }>(settingsUrl, {
        method: "PATCH",
        body: JSON.stringify({
          [field === "apiKey" ? "api_key" : "api_secret"]: value,
        }),
      });
      if (!data?.ok) throw new Error("API bilgisi kaydedilemedi.");
      setActionMessage(data.message || "Binance API bilgisi güvenli şekilde güncellendi.");
      if (field === "apiKey") setApiKey("");
      else setApiSecret("");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "API bilgisi kaydedilemedi.");
    } finally {
      setActiveAction("");
    }
  };

  const handleUpdatePhone = async () => {
    const rawDigits = phone.replace(/\D/g, "");
    if (rawDigits.length < 10) {
      setActionError("En az 10 rakamlı geçerli bir telefon numarası giriniz.");
      return;
    }
    setActiveAction("phone");
    setActionError("");
    setActionMessage("");
    try {
      const data = await apiFetch<{ success?: boolean; message?: string }>("/api/auth/update-phone", {
        method: "POST",
        body: JSON.stringify({ account_id: accountId, phone }),
      });
      if (!data?.success) throw new Error("Telefon numarası güncellenemedi.");
      settingsCache.set(accountId, { ip, name, phone, isIsolated });
      setActionMessage(data.message || "Telefon numaranız güncellendi.");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Telefon numarası güncellenemedi.");
    } finally {
      setActiveAction("");
    }
  };

  const validatePasswordStrength = (p: string) => {
    if (p.length < 10) return "Şifre en az 10 karakter olmalıdır.";
    if (!/[A-Z]/.test(p)) return "Şifre en az 1 büyük harf içermelidir.";
    if (!/[a-z]/.test(p)) return "Şifre en az 1 küçük harf içermelidir.";
    if (!/[0-9]/.test(p)) return "Şifre en az 1 rakam içermelidir.";
    if (!/[.,!?;:]/.test(p)) return "Şifre en az 1 noktalama işareti (.,!?;:) içermelidir.";
    const lowered = p.toLocaleLowerCase("tr-TR");
    const includesProfileName = name
      .split(/\s+/)
      .filter((part) => part.length >= 3)
      .some((part) => lowered.includes(part.toLocaleLowerCase("tr-TR")));
    if (includesProfileName) return "Şifre isim/soyad içeremez.";
    return "";
  };

  const handleUpdatePassword = async () => {
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

    setActiveAction("password");
    try {
      const data = await apiFetch<{ success?: boolean; message?: string }>("/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          account_id: accountId,
          new_password: pass,
          new_password_confirm: confirmPass,
        }),
      });
      if (!data?.success) throw new Error("Şifre güncellenemedi.");
      setPassSuccess(`✓ ${data.message || "Şifreniz başarıyla güncellendi."}`);
      setPass("");
      setConfirmPass("");
    } catch (error) {
      setPassError(error instanceof Error ? error.message : "İşlem gerçekleştirilemedi.");
    } finally {
      setActiveAction("");
    }
  };

  const handleToggleIsolate = async () => {
    const nextVal = !isIsolated;
    setActiveAction("isolate");
    setActionError("");
    setActionMessage("");
    try {
      const data = await apiFetch<{ ok?: boolean; message?: string }>(settingsUrl, {
        method: "PATCH",
        body: JSON.stringify({ isolate_from_admin: nextVal }),
      });
      if (!data?.ok) throw new Error("İzolasyon ayarı değiştirilemedi.");
      setIsIsolated(nextVal);
      settingsCache.set(accountId, { ip, name, phone, isIsolated: nextVal });
      setActionMessage(nextVal ? "Yönetici izolasyonu etkinleştirildi." : "Yönetici izolasyonu kaldırıldı.");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "İzolasyon ayarı değiştirilemedi.");
    } finally {
      setActiveAction("");
    }
  };

  const handleDeleteAccount = async () => {
    setDeleteError("");
    if (!deletePass.trim()) {
      setDeleteError("Şifrenizi giriniz.");
      return;
    }

    setActiveAction("delete");
    try {
      const data = await apiFetch<{ ok?: boolean; message?: string }>(
        `/api/accounts/${accountId}/delete`,
        {
          method: "POST",
          body: JSON.stringify({ password: deletePass }),
          timeoutMs: 20_000,
        },
      );
      if (!data?.ok) throw new Error("Hesap silme işlemi başarısız.");
      setShowDeleteModal(false);
      onLogout();
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "Hesap silme işlemi başarısız.");
    } finally {
      setActiveAction("");
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 shadow-xl space-y-6">
        <h3 className="text-lg font-bold text-white mb-2 flex items-center border-b border-neutral-850 pb-3">
          <Shield className="w-5 h-5 text-[#f0b90b] mr-2" /> Güvenli Hesap Ayarları
        </h3>
        {actionMessage && (
          <p role="status" className="rounded-xl border border-emerald-400/20 bg-emerald-400/5 px-4 py-3 text-xs text-emerald-200">
            {actionMessage}
          </p>
        )}
        {actionError && (
          <p role="alert" className="rounded-xl border border-red-400/20 bg-red-400/5 px-4 py-3 text-xs text-red-200">
            {actionError}
          </p>
        )}

        <PushNotificationSettings accountId={accountId} />

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
                disabled={activeAction === "apiKey"}
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
                disabled={activeAction === "apiSecret"}
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
            <User className="w-3.5 h-3.5 mr-1 text-neutral-400" /> Adı Soyadı
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
              disabled={activeAction === "phone"}
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
            disabled={activeAction === "password"}
            className="w-full py-2.5 bg-neutral-800 hover:bg-neutral-700 text-white font-bold rounded-lg text-sm transition"
          >
            Şifreyi Güncelle
          </button>
        </div>

        {/* Administrative Isolate Toggle block */}
        <div className="hidden">
          <label className="text-xs font-semibold text-neutral-400 flex items-center">
            <ShieldCheck className="w-4 h-4 mr-1 text-[#f0b90b]" /> Adminden İzole Ol
          </label>
          <p className="text-xs text-neutral-500 leading-normal">
            Açıkken V2 yönetim ekranı hesap görünümünü, bakiye ve performans
            değerlerini gizler. Sunucu yöneticilerinin teknik erişim yetkileri bundan
            etkilenmez.
          </p>
          <button
            onClick={handleToggleIsolate}
            disabled={activeAction === "isolate"}
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
            <Trash2 className="w-4 h-4 mr-1 shrink-0" /> Kalıcı Hesap Silme
          </label>
          <p className="text-xs text-neutral-400 leading-normal">
            Hesabınız kalıcı olarak silinecektir. Bu işlem kesinlikle geri alınamaz.
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
                disabled={activeAction === "delete"}
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
