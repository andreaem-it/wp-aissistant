const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function tenantProvider(raw, clientId, provider, accountId) {
  let tenants;
  try { tenants = JSON.parse(raw || "{}"); } catch { return null; }
  const config = tenants[String(clientId)]?.[provider];
  if (!config || String(config.account_id) !== String(accountId) || !config.access_token) return null;
  return config;
}

function first(data, keys) {
  for (const key of keys) {
    const value = String(data?.[key] || "").trim();
    if (value) return value.slice(0, 255);
  }
  return "";
}

export function contactFields(lead) {
  const data = lead?.data || {};
  const email = first(data, ["email", "e_mail", "mail"]);
  if (!EMAIL_RE.test(email)) throw new Error("A valid email is required for CRM idempotency");
  const fullName = first(data, ["nome", "name", "full_name", "nome_completo"]);
  const explicitFirst = first(data, ["firstname", "first_name"]);
  const explicitLast = first(data, ["cognome", "lastname", "last_name"]);
  const parts = fullName.split(/\s+/).filter(Boolean);
  return {
    email,
    firstname: explicitFirst || parts.shift() || "",
    lastname: explicitLast || parts.join(" "),
    phone: first(data, ["telefono", "phone", "tel", "mobile"]),
    company: first(data, ["azienda", "company", "societa", "organization"]),
  };
}

export function brevoUpsert(fields) {
  return {
    email: fields.email,
    attributes: Object.fromEntries(Object.entries({
      FIRSTNAME: fields.firstname, LASTNAME: fields.lastname, SMS: fields.phone, COMPANY: fields.company,
    }).filter(([, value]) => value)),
    updateEnabled: true,
  };
}

export function zohoUpsert(fields) {
  return {
    data: [{
      Email: fields.email,
      Last_Name: fields.lastname || fields.firstname || fields.email,
      ...(fields.firstname ? { First_Name: fields.firstname } : {}),
      ...(fields.phone ? { Phone: fields.phone } : {}),
      ...(fields.company ? { Description: `Azienda: ${fields.company}` } : {}),
    }],
    duplicate_check_fields: ["Email"],
  };
}

export function pipedrivePerson(fields) {
  return {
    name: [fields.firstname, fields.lastname].filter(Boolean).join(" ") || fields.email,
    emails: [{ value: fields.email, primary: true, label: "work" }],
    ...(fields.phone ? { phones: [{ value: fields.phone, primary: true, label: "work" }] } : {}),
  };
}
