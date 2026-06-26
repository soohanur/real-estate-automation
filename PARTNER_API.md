# Funda Property API — Integration Guide

A small private API: send an **address**, get back its **address, days-on-market,
and asking price**.

---

## 1. Your API key

You receive **one secret key** (sent to you separately — not in this file).
It looks like:

```
funda_<random-characters>
```

Rules:
- Keep it **secret**. Store it in your **server** environment variables.
  **Never** put it in front-end / browser code (it would be public).
- Send it on **every** request in the `Authorization` header.
- Always use **HTTPS**.
- If it leaks, tell us and we'll issue a new one.

---

## 2. Endpoint

```
GET https://sons.business/api/v1/partner/property
```

Header (required):
```
Authorization: Bearer YOUR_API_KEY
```

### Query parameters

**Preferred — postcode + house number** (most reliable):
| Param | Example | Notes |
|-------|---------|-------|
| `postcode` | `9801MD` | 4 digits + 2 letters. Spaces/case ignored (`9801 md` works). |
| `house_number` | `4` | Number, optional suffix (`4`, `21A`, `21-3`). |

**Fallback — full address string:**
| Param | Example |
|-------|---------|
| `address` | `Aak 4, 9801 MD Zuidhorn` |

Use **either** `postcode` + `house_number`, **or** `address`.

---

## 3. Response

**Success — `200 OK`**
```json
{
  "address": "Aak 4, 9801 MD Zuidhorn",
  "dom": 35,
  "asking_price": "535000"
}
```
- `address` — the matched property's full address.
- `dom` — days on market (integer; `null` if unknown).
- `asking_price` — asking price in euros, as a plain number string (`"535000"` = €535.000).

**Errors**
| Code | Meaning |
|------|---------|
| `401` | Missing or invalid API key |
| `404` | No matching property found |
| `429` | Too many requests — slow down (limit ~120/min) |
| `400` | Bad request (missing params / query too short) |

---

## 4. Examples

**cURL**
```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  "https://sons.business/api/v1/partner/property?postcode=9801MD&house_number=4"
```

**Node.js (fetch)**
```js
const res = await fetch(
  "https://sons.business/api/v1/partner/property?postcode=9801MD&house_number=4",
  { headers: { Authorization: `Bearer ${process.env.FUNDA_API_KEY}` } }
);
if (res.ok) {
  const data = await res.json();   // { address, dom, asking_price }
} else {
  // handle res.status: 401 / 404 / 429
}
```

**Python (requests)**
```python
import os, requests

r = requests.get(
    "https://sons.business/api/v1/partner/property",
    params={"postcode": "9801MD", "house_number": "4"},
    headers={"Authorization": f"Bearer {os.environ['FUNDA_API_KEY']}"},
)
if r.status_code == 200:
    data = r.json()   # {"address": ..., "dom": ..., "asking_price": ...}
```

---

## 5. Notes

- Matching uses **postcode + house number** (the unique key for Dutch
  addresses). Sending those two is the most reliable.
- If multiple listings match, the **most recent** one is returned.
- New-build / project listings on Funda sometimes have no normal house number;
  those may return `404`.
- Questions or a key reset? Contact us.
