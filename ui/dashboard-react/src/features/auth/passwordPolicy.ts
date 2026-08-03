export function passwordIssue(
  password: string,
  name = "",
  surname = "",
): string | null {
  if (password.length < 10) return "Şifre en az 10 karakter olmalıdır.";
  if (!/[A-Z]/.test(password)) return "En az bir büyük harf kullanın.";
  if (!/[a-z]/.test(password)) return "En az bir küçük harf kullanın.";
  if (!/[0-9]/.test(password)) return "En az bir rakam kullanın.";
  if (!/[.,!?;:]/.test(password)) return "En az bir noktalama işareti kullanın.";
  const lowered = password.toLocaleLowerCase("tr-TR");
  if (name.length >= 3 && lowered.includes(name.toLocaleLowerCase("tr-TR"))) {
    return "Şifre adınızı içeremez.";
  }
  if (surname.length >= 3 && lowered.includes(surname.toLocaleLowerCase("tr-TR"))) {
    return "Şifre soyadınızı içeremez.";
  }
  return null;
}
