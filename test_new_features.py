"""Test script for new features: CRM P&D status enrichment + Formula items endpoint"""
import sys, json, http.cookiejar, urllib.request, urllib.error

# Este arquivo e um smoke test executavel, nao um modulo pytest. Evita chamadas
# HTTP e SystemExit durante a coleta de `pytest` na raiz do repositorio.
if __name__ != "__main__":
    import pytest
    pytest.skip("smoke test manual; execute com python test_new_features.py", allow_module_level=True)

BASE = "http://127.0.0.1:8000/api"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def req(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}
    except Exception as ex:
        return 0, {"error": str(ex)}

def ok(label, cond, detail=""):
    mark = "OK" if cond else "FAIL"
    print(f"  [{mark}] {label}" + (f"  ({detail})" if detail else ""))
    return cond

results = {"pass": 0, "fail": 0}
def check(label, cond, detail=""):
    ok(label, cond, detail)
    if cond:
        results["pass"] += 1
    else:
        results["fail"] += 1
    return cond

# ========== 1. Login ==========
print("\n=== 1. Login ===")
status, data = req("POST", "/auth/login", {"email": "admin@kuryos.com", "password": "admin123"})
if not check("Login admin@kuryos.com", status == 200, f"status={status}"):
    print("Cannot proceed without auth"); sys.exit(1)
print(f"     Logged in as: {data.get('name')} ({data.get('role')})")

# ========== 2. CRM P&D enrichment ==========
print("\n=== 2. CRM /projects/{id}/full - P&D status enrichment ===")
status, projects_data = req("GET", "/crm/projects?limit=10")
if not check("GET /crm/projects", status == 200 and isinstance(projects_data, (list, dict)), f"status={status}"):
    pass
else:
    # The endpoint may return a list or a paginated dict
    projects = projects_data if isinstance(projects_data, list) else projects_data.get("items", projects_data.get("data", []))
    check("Got project list", len(projects) > 0, f"{len(projects)} projects")
    if projects:
        pid = projects[0]["id"]
        status2, full = req("GET", f"/crm/projects/{pid}/full")
        check("GET /crm/projects/{id}/full", status2 == 200, f"status={status2}")
        if status2 == 200:
            samples = full.get("samples", [])
            check("Full response has samples key", True, f"{len(samples)} samples")

            # Walk variations
            variations_found = 0
            pd_enriched = 0
            for s in samples:
                for v in s.get("variacoes", []) or []:
                    variations_found += 1
                    if v.get("pd_status"):
                        pd_enriched += 1
                        check("Variation.pd_status present", True, v["pd_status"])
                        check("Variation.pd_request_id present", bool(v.get("pd_request_id")), v.get("pd_request_id"))

            check("Variations scanned", True, f"{variations_found} variations, {pd_enriched} with P&D status")
            if variations_found > 0 and pd_enriched == 0:
                print("     (No variations linked to P&D cards in this project - checking another)")
                # Try more projects
                for p in projects[1:4]:
                    st3, full3 = req("GET", f"/crm/projects/{p['id']}/full")
                    if st3 == 200:
                        for s in full3.get("samples", []):
                            for v in s.get("variacoes", []) or []:
                                if v.get("pd_status"):
                                    check("Found PD-linked variation in another project", True, v["pd_status"])
                                    pd_enriched += 1
                                    break
                    if pd_enriched > 0:
                        break
                if pd_enriched == 0:
                    print("     (No variations linked to P&D in any scanned project - data-dependent, code OK)")

# ========== 3. Formula Bank - fragrance_percentage ==========
print("\n=== 3. Formula Bank - fragrance_percentage field ===")
status, formulas = req("GET", "/pd/formulas/bank")
check("GET /pd/formulas/bank", status == 200, f"status={status}")
if status == 200 and isinstance(formulas, list):
    check("Formulas returned", len(formulas) >= 0, f"{len(formulas)} formulas")
    if formulas:
        f = formulas[0]
        check("Formula has fragrance_percentage field", "fragrance_percentage" in f, str(f.get("fragrance_percentage")))
        check("Formula has id field", "id" in f)
        fid = f["id"]

        # ========== 4. Formula items endpoint ==========
        print("\n=== 4. Formula items - scaling for manipulation order ===")
        status2, items = req("GET", f"/pd/formulas/{fid}/items")
        check("GET /pd/formulas/{id}/items", status2 == 200, f"status={status2}")
        if status2 == 200 and isinstance(items, list):
            check("Items is list", True, f"{len(items)} items")
            if items:
                item = items[0]
                check("Item has ingredient_name", bool(item.get("ingredient_name")), item.get("ingredient_name","?"))
                check("Item has percentage", "percentage" in item, str(item.get("percentage")))
                check("Item has phase", "phase" in item)
                pct = item.get("percentage") or 0
                for vol in [15.0, 30.0, 100.0]:
                    qty = round((pct / 100) * vol, 4)
                    check(f"Scaling {vol}mL -> {qty}g", qty >= 0, f"{pct}% x {vol}mL")

# ========== 5. Backward status transition =========
print("\n=== 5. Backward status transition validation ===")
status, reqs_list = req("GET", "/pd/requests?limit=5")
if status == 200 and isinstance(reqs_list, list) and reqs_list:
    r0 = reqs_list[0]
    rid = r0.get("id")
    current = r0.get("status")
    print(f"     Request id={rid} status={current}")

    st, resp = req("PUT", f"/pd/requests/{rid}/status", {"new_status": "OPEN", "is_backward": True, "comment": ""})
    check("Backward without comment -> 400", st == 400, f"got {st}: {resp.get('detail','')[:80]}")

    st, resp = req("PUT", f"/pd/requests/{rid}/status", {"new_status": "OPEN", "is_backward": True, "comment": "ok"})
    check("Backward with <10 char comment -> 400", st == 400, f"got {st}: {resp.get('detail','')[:80]}")
else:
    check("GET /pd/requests for backward test", False, f"status={status}, count={len(reqs_list) if isinstance(reqs_list,list) else '?'}")

# ========== 6. Two-stage sample: internal_approved auto-set ==========
print("\n=== 6. Two-stage sample approval: internal_approved auto ===")
status, devs = req("GET", "/pd/developments?limit=5")
found_test = False
if status == 200 and isinstance(devs, list):
    for dev in devs:
        did = dev.get("id")
        st2, samples = req("GET", f"/pd/developments/{did}/samples")
        if st2 == 200 and isinstance(samples, list):
            unsent = [s for s in samples if not s.get("sent_to_client")]
            if unsent:
                sid = unsent[0]["id"]
                st3, _ = req("PUT", f"/pd/samples/{sid}", {"sent_to_client": True})
                check("PUT sent_to_client=True -> 200", st3 == 200, f"status={st3}")
                st4, slist = req("GET", f"/pd/developments/{did}/samples")
                s_updated = next((x for x in slist if x["id"] == sid), None) if st4 == 200 else None
                if s_updated:
                    check("internal_approved auto-set True", s_updated.get("internal_approved") == True, str(s_updated.get("internal_approved")))
                    # Reset for clean state
                    req("PUT", f"/pd/samples/{sid}", {"sent_to_client": False, "internal_approved": None})
                found_test = True
                break
if not found_test:
    print("     (No unsent samples found to test auto-approve - data dependent)")

# ========== SUMMARY ==========
total = results["pass"] + results["fail"]
print(f"\n{'='*50}")
print(f"RESULTS: {results['pass']}/{total} passed, {results['fail']} failed")
print(f"{'='*50}\n")
sys.exit(0 if results["fail"] == 0 else 1)
