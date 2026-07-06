"""CP-Vault-ACL probe (Milestone 0): empirically settle the macOS credential
vault's #1 risk - which Security.framework construction yields a login-keychain
generic-password item with a TRUE allow-all ACL that fires ZERO access prompts.

The design (docs/superpowers/specs/2026-07-06-macos-credential-vault-touchid-
design.md) stores every secret in ONE login-keychain item read with no prompt
after macOS login. That hinges on an allow-all ACL, and SecAccessCreate(NULL) can
mean "current app trusted", not "any app" - so the recipe cannot be trusted from
reasoning (IRON LAW: behaviour needs an empirical probe). This probe builds the
item several ways, dumps each resulting ACL, and lets the OPERATOR watch which
one prompts and which reads "Allow all applications to access this item" in
Keychain Access.

WHAT IT PROVES (five labelled sections + a verdict):
  A - allow-all ACL construction: A1 SecAccessCreate(NULL trusted list),
      A2 SecAccessCreate(empty trusted CFArray), A3 SecAccessCreate + rewrite each
      ACL's contents with a NULL application list (the canonical allow-all move).
      Each is added via SecItemAdd(kSecAttrAccess=access); the resulting ACL is
      dumped so allow-all vs current-app-only is visible.
  B - reference baseline: `/usr/bin/security add-generic-password -A -U` (the
      known allow-all) so the framework ACLs can be diffed against it.
  C - prompt behaviour: read each item twice, UPDATE its value, read once more,
      and re-dump the ACL - proving whether SecItemUpdate PRESERVES allow-all.
  D - LocalAuthentication: LAContext canEvaluatePolicy + evaluatePolicy once,
      proving Touch ID / password / watch works on the ad-hoc/from-source
      identity with no entitlement.
  E - data-protection keychain: SecItemAdd(kSecUseDataProtectionKeychain) with a
      SecAccessControl; the design expects errSecMissingEntitlement (-34018) on
      this ad-hoc build - this confirms it.

ISOLATION: HOME + TTMT_CONFIG_DIR are redirected to a throwaway tmp dir at import
time (project IRON LAW - protects the app's real config). Because HOME also steers
the default keychain, this probe deliberately targets the REAL login keychain by
its absolute path (resolved from the OS user record, independent of HOME), so it
observes real prompt/ACL behaviour while never touching TTMT's config. Every item
it creates lives under the throwaway service "__ttmt_vault_probe__" and is deleted
in a finally block. It never imports MultitoonTab / CredentialsManager / the input
service and never touches the real service names.

The bindings for Security / SecKeychain / SecACL / LocalAuthentication are C (or
ObjC), driven here through ctypes + a thin PyObjC bridge for readability - the same
idioms as utils/macos_platform_binary.py and .../keyring/backends/macOS/api.py.

RUN IT ON THE REAL cocoa SESSION (it touches the real Keychain and may pop
dialogs - the operator, not the author, runs it):

    ./venv/bin/python scripts/probes/credentials/cp_vault_acl.py

Follow the printed operator steps; note which sections pop a prompt and which do
not, then open Keychain Access to confirm the ACL wording. Record the outcome in
docs/superpowers/specs/2026-07-06-macos-credential-vault-touchid-probe-ledger.md
(Task 0.2).
"""
# --- config isolation FIRST (IRON LAW: HOME + TTMT_CONFIG_DIR -> tmp before any
# import that could read the real config). Done before ctypes/objc load. ---
import os
import tempfile

_ISO_DIR = tempfile.mkdtemp(prefix="ttmt_vault_probe_")
os.environ["HOME"] = _ISO_DIR
os.environ["TTMT_CONFIG_DIR"] = _ISO_DIR

import ctypes
from ctypes import POINTER, byref, c_char_p, c_int32, c_long, c_uint16, c_uint32, c_void_p
from ctypes.util import find_library
import platform
import pwd
import subprocess
import sys
import threading

# Throwaway service literal for EVERY item this probe creates. Never the real
# keyring_service() / cc_token_service() names.
SERVICE = "__ttmt_vault_probe__"

# Framework-created accounts (Step A) + the CLI reference (Step B) + the DP attempt
# (Step E). Cleanup deletes all of these under SERVICE.
ACC_A1 = "a1_seccreate_null"       # SecAccessCreate(NULL trusted list)
ACC_A2 = "a2_seccreate_empty"      # SecAccessCreate(empty trusted CFArray)
ACC_A3 = "a3_acl_null_applist"     # SecAccessCreate + SecACLSetContents(NULL app list)
ACC_REF = "refbaseline"            # security add-generic-password -A -U
ACC_E = "e_dataprotection"         # kSecUseDataProtectionKeychain attempt
ALL_ACCOUNTS = [ACC_A1, ACC_A2, ACC_A3, ACC_REF, ACC_E]

# Throwaway secrets. Framework items pass the secret via CFData (never argv); the
# CLI reference necessarily puts its throwaway secret on argv (-w) - acceptable
# for a probe.
SECRET = "cp-vault-probe-secret-v1"
SECRET_UPDATED = "cp-vault-probe-secret-v2-updated"
REF_SECRET = "cp-vault-probe-ref-secret"

_UTF8 = 0x08000100  # kCFStringEncodingUTF8

# Real OS user home, resolved from the passwd record so it survives the HOME
# override above. The real login keychain lives under it.
_REAL_HOME = pwd.getpwuid(os.getuid()).pw_dir

# LAPolicyDeviceOwnerAuthentication (Touch ID | password | watch) and
# LAPolicyDeviceOwnerAuthenticationWithBiometrics.
_LA_POLICY_DEVICE_OWNER = 2
_LA_POLICY_BIOMETRICS = 1

# SecAccessControlCreateFlags.
_SAC_USER_PRESENCE = 1 << 0        # kSecAccessControlUserPresence
_SAC_BIOMETRY_CURRENT_SET = 1 << 3  # kSecAccessControlBiometryCurrentSet

_KNOWN_STATUS = {
    0: "errSecSuccess",
    -25291: "errSecNotAvailable",
    -25293: "errSecAuthFailed",
    -25300: "errSecItemNotFound",
    -25308: "errSecInteractionNotAllowed",
    -34018: "errSecMissingEntitlement",
    -128: "errSecUserCanceled",
}


# ---------------------------------------------------------------------------
# ctypes bindings against Security + CoreFoundation (typed once, module level).
# ---------------------------------------------------------------------------

_OSStatus = c_int32
_sec = ctypes.CDLL(find_library("Security"))
_cf = ctypes.CDLL(find_library("CoreFoundation"))


def _bind(lib, name, restype, argtypes):
    fn = getattr(lib, name)
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


CFStringCreateWithCString = _bind(_cf, "CFStringCreateWithCString", c_void_p,
                                  [c_void_p, c_char_p, c_uint32])
CFDataCreate = _bind(_cf, "CFDataCreate", c_void_p, [c_void_p, c_char_p, c_long])
CFDataGetBytePtr = _bind(_cf, "CFDataGetBytePtr", c_void_p, [c_void_p])
CFDataGetLength = _bind(_cf, "CFDataGetLength", c_long, [c_void_p])
CFDictionaryCreate = _bind(_cf, "CFDictionaryCreate", c_void_p,
                           [c_void_p, c_void_p, c_void_p, c_long, c_void_p, c_void_p])
CFArrayCreate = _bind(_cf, "CFArrayCreate", c_void_p,
                      [c_void_p, c_void_p, c_long, c_void_p])
CFArrayGetCount = _bind(_cf, "CFArrayGetCount", c_long, [c_void_p])
CFArrayGetValueAtIndex = _bind(_cf, "CFArrayGetValueAtIndex", c_void_p, [c_void_p, c_long])

# Pointers to the CF callback structs (CFDictionary/CFArray want &callbacks).
_DICT_KEY_CB = ctypes.addressof(c_void_p.in_dll(_cf, "kCFTypeDictionaryKeyCallBacks"))
_DICT_VAL_CB = ctypes.addressof(c_void_p.in_dll(_cf, "kCFTypeDictionaryValueCallBacks"))
_ARRAY_CB = ctypes.addressof(c_void_p.in_dll(_cf, "kCFTypeArrayCallBacks"))
_CF_TRUE = c_void_p.in_dll(_cf, "kCFBooleanTrue").value
_CF_FALSE = c_void_p.in_dll(_cf, "kCFBooleanFalse").value

SecItemAdd = _bind(_sec, "SecItemAdd", _OSStatus, [c_void_p, c_void_p])
SecItemCopyMatching = _bind(_sec, "SecItemCopyMatching", _OSStatus, [c_void_p, c_void_p])
SecItemUpdate = _bind(_sec, "SecItemUpdate", _OSStatus, [c_void_p, c_void_p])
SecItemDelete = _bind(_sec, "SecItemDelete", _OSStatus, [c_void_p])
SecKeychainOpen = _bind(_sec, "SecKeychainOpen", _OSStatus, [c_char_p, POINTER(c_void_p)])
SecAccessCreate = _bind(_sec, "SecAccessCreate", _OSStatus,
                        [c_void_p, c_void_p, POINTER(c_void_p)])
SecAccessCopyACLList = _bind(_sec, "SecAccessCopyACLList", _OSStatus,
                             [c_void_p, POINTER(c_void_p)])
SecACLCopyContents = _bind(_sec, "SecACLCopyContents", _OSStatus,
                           [c_void_p, POINTER(c_void_p), POINTER(c_void_p), POINTER(c_uint16)])
SecACLSetContents = _bind(_sec, "SecACLSetContents", _OSStatus,
                          [c_void_p, c_void_p, c_void_p, c_uint16])
SecACLCopyAuthorizations = _bind(_sec, "SecACLCopyAuthorizations", c_void_p, [c_void_p])
SecKeychainItemCopyAccess = _bind(_sec, "SecKeychainItemCopyAccess", _OSStatus,
                                  [c_void_p, POINTER(c_void_p)])
SecTrustedApplicationCopyData = _bind(_sec, "SecTrustedApplicationCopyData", _OSStatus,
                                      [c_void_p, POINTER(c_void_p)])
SecAccessControlCreateWithFlags = _bind(_sec, "SecAccessControlCreateWithFlags", c_void_p,
                                        [c_void_p, c_void_p, ctypes.c_ulong, POINTER(c_void_p)])
try:
    SecCopyErrorMessageString = _bind(_sec, "SecCopyErrorMessageString", c_void_p,
                                      [_OSStatus, c_void_p])
except Exception:
    SecCopyErrorMessageString = None


# ---------------------------------------------------------------------------
# small CF helpers
# ---------------------------------------------------------------------------

def _cfstr(s: str) -> int:
    return CFStringCreateWithCString(None, s.encode("utf-8"), _UTF8)


def _cfdata(b: bytes) -> int:
    return CFDataCreate(None, b, len(b))


def _cfarray(ptrs) -> int:
    n = len(ptrs)
    arr = (c_void_p * n)(*[c_void_p(p) for p in ptrs])
    return CFArrayCreate(None, arr, n, _ARRAY_CB)


def _k(name: str) -> int:
    """Security CFString constant pointer as an int address. Raises a clearly
    labelled error if a constant is unexpectedly missing on this OS."""
    try:
        return c_void_p.in_dll(_sec, name).value
    except Exception as e:
        raise RuntimeError(f"MISSING Security constant {name}: {e}")


def _to_ptr(value) -> int:
    """Coerce a Python value to the CF pointer address SecItem* wants."""
    if isinstance(value, bool):
        return _CF_TRUE if value else _CF_FALSE
    if isinstance(value, int):           # already a CF pointer address / constant
        return value
    if isinstance(value, c_void_p):
        return value.value or 0
    if isinstance(value, bytes):
        return _cfdata(value)
    if isinstance(value, str):
        return _cfstr(value)
    raise TypeError(f"unsupported query value {value!r}")


def _make_query(items: dict) -> int:
    """Build a CFDictionary from {constant_name: value}. Mirrors keyring's
    create_query but understands bytes (-> CFData), bool (-> kCFBoolean*) and
    raw CF pointers (passed through)."""
    keys = list(items.keys())
    n = len(keys)
    key_arr = (c_void_p * n)(*[c_void_p(_k(name)) for name in keys])
    val_arr = (c_void_p * n)(*[c_void_p(_to_ptr(items[name])) for name in keys])
    return CFDictionaryCreate(None, key_arr, val_arr, n, _DICT_KEY_CB, _DICT_VAL_CB)


def _cf_to_str(ptr) -> str:
    """Wrap a CFStringRef/NSString pointer as a Python str via the PyObjC bridge."""
    if not ptr:
        return ""
    try:
        import objc
        return str(objc.objc_object(c_void_p=int(ptr)))
    except Exception as e:
        return f"<cfstr err {e}>"


def _cfarray_of_str(ptr) -> list:
    if not ptr:
        return []
    try:
        import objc
        return [str(x) for x in objc.objc_object(c_void_p=int(ptr))]
    except Exception as e:
        return [f"<cfarray err {e}>"]


def status_str(st: int) -> str:
    name = _KNOWN_STATUS.get(int(st), "")
    msg = ""
    if SecCopyErrorMessageString is not None:
        try:
            p = SecCopyErrorMessageString(int(st), None)
            if p:
                msg = _cf_to_str(p)
        except Exception:
            msg = ""
    parts = [str(int(st))]
    if name:
        parts.append(name)
    if msg and msg != name:
        parts.append(f'"{msg}"')
    return " ".join(parts)


def _section(title: str) -> None:
    print(f"\n==== {title} ====", flush=True)


# ---------------------------------------------------------------------------
# real login keychain (targeted explicitly so the HOME override cannot point us
# at an empty tmp keychain)
# ---------------------------------------------------------------------------

_KC = c_void_p()  # SecKeychainRef of the real login keychain
_KC_PATH = ""


def _resolve_login_keychain_path() -> str:
    kc_dir = os.path.join(_REAL_HOME, "Library", "Keychains")
    for name in ("login.keychain-db", "login.keychain"):
        p = os.path.join(kc_dir, name)
        if os.path.exists(p):
            return p
    # Neither on disk (unusual) - hand SecKeychainOpen the modern name anyway so
    # there is a concrete path to report; the operator will see the open status.
    return os.path.join(kc_dir, "login.keychain-db")


def _open_login_keychain() -> bool:
    global _KC_PATH
    _KC_PATH = _resolve_login_keychain_path()
    st = SecKeychainOpen(_KC_PATH.encode("utf-8"), byref(_KC))
    print(f"[keychain] path={_KC_PATH}", flush=True)
    print(f"[keychain] exists={os.path.exists(_KC_PATH)} SecKeychainOpen={status_str(st)} "
          f"ref={'yes' if _KC.value else 'NULL'}", flush=True)
    return bool(_KC.value)


def _search_list_items() -> dict:
    """kSecMatchSearchList scoping the real login keychain (only when open)."""
    return {"kSecMatchSearchList": _cfarray([_KC.value])} if _KC.value else {}


# ---------------------------------------------------------------------------
# item add / read / update / delete (framework path, scoped to the real login
# keychain)
# ---------------------------------------------------------------------------

def add_generic(account: str, secret: str, access_ptr=None) -> int:
    items = {
        "kSecClass": _k("kSecClassGenericPassword"),
        "kSecAttrService": SERVICE,
        "kSecAttrAccount": account,
        "kSecValueData": secret.encode("utf-8"),
    }
    if _KC.value:
        items["kSecUseKeychain"] = _KC.value
    if access_ptr:
        items["kSecAttrAccess"] = access_ptr
    return SecItemAdd(_make_query(items), None)


def read_generic(account: str):
    """(status, value_or_None). Reading the DATA is what triggers an ACL prompt."""
    items = {
        "kSecClass": _k("kSecClassGenericPassword"),
        "kSecAttrService": SERVICE,
        "kSecAttrAccount": account,
        "kSecMatchLimit": _k("kSecMatchLimitOne"),
        "kSecReturnData": True,
    }
    items.update(_search_list_items())
    out = c_void_p()
    st = SecItemCopyMatching(_make_query(items), byref(out))
    if st != 0 or not out.value:
        return st, None
    raw = ctypes.string_at(CFDataGetBytePtr(out), CFDataGetLength(out))
    try:
        return st, raw.decode("utf-8")
    except Exception:
        return st, raw


def update_generic(account: str, new_secret: str) -> int:
    query = {
        "kSecClass": _k("kSecClassGenericPassword"),
        "kSecAttrService": SERVICE,
        "kSecAttrAccount": account,
    }
    query.update(_search_list_items())
    attrs = {"kSecValueData": new_secret.encode("utf-8")}
    return SecItemUpdate(_make_query(query), _make_query(attrs))


def delete_generic(account: str, data_protection: bool = False) -> int:
    items = {
        "kSecClass": _k("kSecClassGenericPassword"),
        "kSecAttrService": SERVICE,
        "kSecAttrAccount": account,
    }
    if data_protection:
        items["kSecUseDataProtectionKeychain"] = True
    else:
        items.update(_search_list_items())
    return SecItemDelete(_make_query(items))


# ---------------------------------------------------------------------------
# ACL dump: NULL application list on the decrypt ACL == "allow all applications"
# ---------------------------------------------------------------------------

def _trusted_app_paths(app_list_ptr) -> list:
    paths = []
    try:
        n = CFArrayGetCount(app_list_ptr)
        for i in range(min(int(n), 5)):
            app = CFArrayGetValueAtIndex(app_list_ptr, i)
            d = c_void_p()
            if SecTrustedApplicationCopyData(app, byref(d)) == 0 and d.value:
                raw = ctypes.string_at(CFDataGetBytePtr(d), CFDataGetLength(d))
                paths.append(raw.split(b"\x00", 1)[0].decode("utf-8", "replace"))
    except Exception as e:
        paths.append(f"<err {e}>")
    return paths


def describe_acl(label: str, account: str) -> dict:
    """Dump every ACL of the item's SecAccess. Returns {found, allow_all} where
    allow_all is True iff the decrypt/read ACL trusts ALL apps (NULL app list)."""
    info = {"found": False, "allow_all": None}
    items = {
        "kSecClass": _k("kSecClassGenericPassword"),
        "kSecAttrService": SERVICE,
        "kSecAttrAccount": account,
        "kSecMatchLimit": _k("kSecMatchLimitOne"),
        "kSecReturnRef": True,
    }
    items.update(_search_list_items())
    ref = c_void_p()
    st = SecItemCopyMatching(_make_query(items), byref(ref))
    if st != 0 or not ref.value:
        print(f"[acl {label}] {account}: not found ({status_str(st)})", flush=True)
        return info
    info["found"] = True
    access = c_void_p()
    st = SecKeychainItemCopyAccess(ref, byref(access))
    if st != 0 or not access.value:
        print(f"[acl {label}] {account}: SecKeychainItemCopyAccess failed "
              f"({status_str(st)})", flush=True)
        return info
    acl_list = c_void_p()
    st = SecAccessCopyACLList(access, byref(acl_list))
    if st != 0 or not acl_list.value:
        print(f"[acl {label}] {account}: SecAccessCopyACLList failed "
              f"({status_str(st)})", flush=True)
        return info
    n = int(CFArrayGetCount(acl_list))
    allow_all_decrypt = False
    print(f"[acl {label}] {account}: {n} ACL(s)", flush=True)
    for i in range(n):
        acl = CFArrayGetValueAtIndex(acl_list, i)
        app_list = c_void_p()
        desc = c_void_p()
        psel = c_uint16(0)
        cst = SecACLCopyContents(acl, byref(app_list), byref(desc), byref(psel))
        auths = _cfarray_of_str(SecACLCopyAuthorizations(acl))
        if cst != 0:
            print(f"    ACL[{i}] SecACLCopyContents failed ({status_str(cst)}) "
                  f"auths={auths}", flush=True)
            continue
        if app_list.value:
            napps = int(CFArrayGetCount(app_list))
            trusted = f"count={napps} {_trusted_app_paths(app_list)}"
        else:
            trusted = "ALL(NULL app list -> allow-all)"
        is_decrypt = any("Decrypt" in a for a in auths)
        if is_decrypt and not app_list.value:
            allow_all_decrypt = True
        print(f"    ACL[{i}] auths={auths} desc={_cf_to_str(desc.value)!r} "
              f"prompt={psel.value} trustedApps={trusted}", flush=True)
    info["allow_all"] = allow_all_decrypt
    print(f"[acl {label}] {account}: decrypt-ACL allow-all = {allow_all_decrypt}", flush=True)
    return info


# ---------------------------------------------------------------------------
# SecAccess constructions
# ---------------------------------------------------------------------------

def _access_create(trusted_list_ptr, descriptor: str):
    access = c_void_p()
    st = SecAccessCreate(_cfstr(descriptor), trusted_list_ptr, byref(access))
    return st, access


def build_access_a1():
    """A1: SecAccessCreate(NULL trusted list). Design suspects this trusts only
    the CURRENT app, not all apps - dumped so we can see."""
    return _access_create(None, "ttmt vault probe A1 (null trusted list)")


def build_access_a2():
    """A2: SecAccessCreate(EMPTY trusted CFArray) - historically 'no apps
    trusted' (prompt), the opposite of allow-all; included as a contrast."""
    return _access_create(_cfarray([]), "ttmt vault probe A2 (empty trusted list)")


def build_access_a3():
    """A3: SecAccessCreate(NULL) then rewrite EVERY ACL's contents with a NULL
    application list via SecACLSetContents - the canonical 'allow all
    applications' construction."""
    st, access = _access_create(None, "ttmt vault probe A3 (allow-all)")
    if st != 0 or not access.value:
        return st, access
    acl_list = c_void_p()
    st2 = SecAccessCopyACLList(access, byref(acl_list))
    if st2 != 0 or not acl_list.value:
        print(f"[A3] SecAccessCopyACLList failed ({status_str(st2)})", flush=True)
        return st, access
    n = int(CFArrayGetCount(acl_list))
    for i in range(n):
        acl = CFArrayGetValueAtIndex(acl_list, i)
        # applicationList = NULL -> allow all; promptSelector = 0 -> no passphrase.
        sst = SecACLSetContents(acl, None, _cfstr("ttmt vault probe A3 (allow-all)"), 0)
        if sst != 0:
            print(f"[A3] SecACLSetContents ACL[{i}] failed ({status_str(sst)})", flush=True)
    return st, access


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step_a(results: dict) -> None:
    _section("STEP A - allow-all ACL constructions (Security.framework)")
    print("Each construction adds one generic-password item, then dumps its ACL.\n"
          "Watch for any GUI prompt while these ADD/dump.", flush=True)
    plan = [
        ("A1", ACC_A1, build_access_a1),
        ("A2", ACC_A2, build_access_a2),
        ("A3", ACC_A3, build_access_a3),
    ]
    for label, account, builder in plan:
        try:
            # Fresh add: clear any stale item from a prior aborted run first.
            delete_generic(account)
            st_acc, access = builder()
            print(f"[{label}] SecAccessCreate -> {status_str(st_acc)} "
                  f"access={'yes' if access.value else 'NULL'}", flush=True)
            st_add = add_generic(account, SECRET, access.value if access.value else None)
            print(f"[{label}] SecItemAdd({account}) -> {status_str(st_add)}", flush=True)
            acl = describe_acl(label, account)
            results[label] = {"add": int(st_add), "found": acl["found"],
                              "allow_all": acl["allow_all"]}
        except Exception as e:
            print(f"[{label}] FAILED: {type(e).__name__}: {e}", flush=True)
            results[label] = {"error": f"{type(e).__name__}: {e}"}


def step_b(results: dict) -> None:
    _section("STEP B - reference baseline (security add-generic-password -A -U)")
    security = "/usr/bin/security"
    # Explicit keychain path so the child never targets the HOME=tmp keychain;
    # HOME=real in the child env keeps `security` and Keychain Access consistent.
    child_env = dict(os.environ)
    child_env["HOME"] = _REAL_HOME
    argv = [security, "add-generic-password", "-A", "-U",
            "-s", SERVICE, "-a", ACC_REF, "-w", REF_SECRET, _KC_PATH]
    try:
        # -U updates in place if it already exists, so a prior run is fine.
        proc = subprocess.run(argv, env=child_env, capture_output=True, text=True, timeout=30)
        print(f"[ref] `security add-generic-password -A -U` rc={proc.returncode}", flush=True)
        if proc.stdout.strip():
            print(f"[ref] stdout: {proc.stdout.strip()}", flush=True)
        if proc.stderr.strip():
            print(f"[ref] stderr: {proc.stderr.strip()}", flush=True)
        acl = describe_acl("ref", ACC_REF)
        results["ref"] = {"rc": proc.returncode, "found": acl["found"],
                          "allow_all": acl["allow_all"]}
    except Exception as e:
        print(f"[ref] FAILED: {type(e).__name__}: {e}", flush=True)
        results["ref"] = {"error": f"{type(e).__name__}: {e}"}
    print("\n[ref] OPERATOR: open Keychain Access -> login keychain -> search "
          f'"{SERVICE}". For each item open Access Control and confirm whether it '
          'reads "Allow all applications to access this item".', flush=True)


def step_c(results: dict) -> None:
    _section("STEP C - prompt behaviour: read x2, UPDATE, read, re-dump ACL")
    print("If an item is truly allow-all, none of these should prompt.\n"
          "The re-dump after UPDATE proves whether SecItemUpdate PRESERVES the "
          "allow-all ACL (design re-applies it on every write; this shows if a "
          "bare update already keeps it).", flush=True)
    targets = [("A1", ACC_A1), ("A2", ACC_A2), ("A3", ACC_A3), ("ref", ACC_REF)]
    results.setdefault("C", {})
    for label, account in targets:
        try:
            r1 = read_generic(account)
            r2 = read_generic(account)
            print(f"[C {label}] read#1 {status_str(r1[0])} "
                  f"value={'<got %d chars>' % len(r1[1]) if r1[1] else 'None'}", flush=True)
            print(f"[C {label}] read#2 {status_str(r2[0])} "
                  f"value={'<got %d chars>' % len(r2[1]) if r2[1] else 'None'}", flush=True)
            up = update_generic(account, SECRET_UPDATED)
            print(f"[C {label}] SecItemUpdate -> {status_str(up)}", flush=True)
            r3 = read_generic(account)
            got3 = r3[1] == SECRET_UPDATED if isinstance(r3[1], str) else False
            print(f"[C {label}] read#3 (post-update) {status_str(r3[0])} "
                  f"value={'<got %d chars>' % len(r3[1]) if r3[1] else 'None'} "
                  f"updated_value_seen={got3}", flush=True)
            acl = describe_acl(f"{label}/post-update", account)
            results["C"][label] = {
                "read1": int(r1[0]), "read2": int(r2[0]),
                "update": int(up), "read3": int(r3[0]),
                "allow_all_after_update": acl["allow_all"],
            }
        except Exception as e:
            print(f"[C {label}] FAILED: {type(e).__name__}: {e}", flush=True)
            results["C"][label] = {"error": f"{type(e).__name__}: {e}"}


def step_d(results: dict) -> None:
    _section("STEP D - LocalAuthentication (LAContext evaluatePolicy)")
    la_out = {"binding": None, "can_device_owner": None, "can_biometrics": None,
              "biometry_type": None, "evaluated": None, "factor": None}
    try:
        import objc
    except Exception as e:
        print(f"[D] objc unavailable: {e}", flush=True)
        results["D"] = {"error": f"objc unavailable: {e}"}
        return

    LAContext = None
    try:
        import LocalAuthentication as _LA  # pyobjc-framework-LocalAuthentication
        LAContext = _LA.LAContext
        la_out["binding"] = "pyobjc"
        print("[D] using PyObjC LocalAuthentication binding", flush=True)
    except Exception:
        print("MISSING BINDING: LocalAuthentication "
              "(add pyobjc-framework-LocalAuthentication to requirements)", flush=True)
        # ctypes fallback: load the framework so its ObjC classes register, then
        # teach PyObjC the two selector signatures (no framework metadata present).
        try:
            ctypes.CDLL(find_library("LocalAuthentication"))
            c_out = getattr(objc, "_C_OUT", b"o")
            c_nsbool = getattr(objc, "_C_NSBOOL", b"Z")
            try:
                objc.registerMetaDataForSelector(
                    b"LAContext", b"canEvaluatePolicy:error:",
                    {"arguments": {3: {"type": b"^@", "type_modifier": c_out,
                                       "null_accepted": True}}})
                objc.registerMetaDataForSelector(
                    b"LAContext", b"evaluatePolicy:localizedReason:reply:",
                    {"arguments": {4: {"callable": {
                        "retval": {"type": b"v"},
                        "arguments": {0: {"type": b"^v"}, 1: {"type": c_nsbool},
                                      2: {"type": b"@"}}}}}})
            except Exception as me:
                print(f"[D] registerMetaDataForSelector warning: {me}", flush=True)
            LAContext = objc.lookUpClass("LAContext")
            la_out["binding"] = "ctypes-fallback"
            print("[D] bootstrapped LAContext via ctypes fallback", flush=True)
        except Exception as e:
            print(f"[D] could not bootstrap LAContext: {type(e).__name__}: {e}", flush=True)
            results["D"] = {"error": f"LAContext bootstrap failed: {e}"}
            return

    try:
        ctx = LAContext.alloc().init()
    except Exception as e:
        print(f"[D] LAContext alloc/init failed: {e}", flush=True)
        results["D"] = {"error": f"alloc/init failed: {e}"}
        return

    def _can(policy):
        try:
            r = ctx.canEvaluatePolicy_error_(policy, None)
            if isinstance(r, tuple):
                ok, err = r[0], r[1]
            else:
                ok, err = r, None
            return bool(ok), err
        except Exception as e:
            return None, e

    can_do, err_do = _can(_LA_POLICY_DEVICE_OWNER)
    can_bio, err_bio = _can(_LA_POLICY_BIOMETRICS)
    la_out["can_device_owner"] = can_do
    la_out["can_biometrics"] = can_bio
    print(f"[D] canEvaluatePolicy(deviceOwnerAuthentication)={can_do} err={err_do}", flush=True)
    print(f"[D] canEvaluatePolicy(withBiometrics)={can_bio} err={err_bio}", flush=True)
    try:
        bt = int(ctx.biometryType())
        la_out["biometry_type"] = bt
        bt_name = {0: "none", 1: "touchid", 2: "faceid(N/A on macOS)"}.get(bt, str(bt))
        print(f"[D] biometryType={bt} ({bt_name})", flush=True)
    except Exception as e:
        print(f"[D] biometryType unavailable: {e}", flush=True)

    if can_do is False:
        print("[D] deviceOwnerAuthentication not evaluable (no Touch ID / "
              "password / watch?) - skipping evaluatePolicy.", flush=True)
        results["D"] = la_out
        return

    print("\n[D] OPERATOR: a Touch ID / password prompt should appear now - "
          "respond to it (this is the app's own unlock gate, the ONLY prompt the "
          "shipped design shows).", flush=True)
    done = threading.Event()
    reply = {"success": None, "error": None}

    def _reply(success, error):
        reply["success"] = bool(success)
        reply["error"] = error
        done.set()

    try:
        ctx.evaluatePolicy_localizedReason_reply_(
            _LA_POLICY_DEVICE_OWNER, "Unlock your ToonTown MultiTool accounts", _reply)
    except Exception as e:
        print(f"[D] evaluatePolicy call failed (likely block-bridging without the "
              f"PyObjC binding): {type(e).__name__}: {e}", flush=True)
        print("[D] Install pyobjc-framework-LocalAuthentication and re-run for the "
              "evaluatePolicy leg.", flush=True)
        la_out["evaluated"] = f"call-failed: {e}"
        results["D"] = la_out
        return

    if not done.wait(90):
        print("[D] evaluatePolicy timed out after 90s (no operator response).", flush=True)
        la_out["evaluated"] = "timeout"
    else:
        la_out["evaluated"] = reply["success"]
        # No public API reports WHICH factor authenticated; infer from availability.
        if reply["success"]:
            if la_out.get("biometry_type"):
                la_out["factor"] = "touchid (or watch/password fallback)"
            else:
                la_out["factor"] = "password/watch (no biometry configured)"
        print(f"[D] evaluatePolicy success={reply['success']} error={reply['error']} "
              f"inferred_factor={la_out['factor']}", flush=True)
    results["D"] = la_out


def step_e(results: dict) -> None:
    _section("STEP E - data-protection keychain (expect errSecMissingEntitlement)")
    print("The design expects -34018 errSecMissingEntitlement on an ad-hoc build, "
          "which cleanly selects the login-keychain allow-all path.", flush=True)
    try:
        err = c_void_p()
        protection = _k("kSecAttrAccessibleWhenUnlockedThisDeviceOnly")
        flags = _SAC_BIOMETRY_CURRENT_SET
        ac = SecAccessControlCreateWithFlags(None, c_void_p(protection), flags, byref(err))
        if not ac:
            # biometryCurrentSet can fail if no biometry enrolled; retry userPresence.
            print(f"[E] SecAccessControl(biometryCurrentSet) failed err={err.value}; "
                  "retrying userPresence", flush=True)
            err = c_void_p()
            ac = SecAccessControlCreateWithFlags(None, c_void_p(protection),
                                                 _SAC_USER_PRESENCE, byref(err))
        print(f"[E] SecAccessControlCreateWithFlags -> "
              f"{'ok' if ac else 'NULL'}", flush=True)
        items = {
            "kSecClass": _k("kSecClassGenericPassword"),
            "kSecAttrService": SERVICE,
            "kSecAttrAccount": ACC_E,
            "kSecValueData": SECRET.encode("utf-8"),
            "kSecUseDataProtectionKeychain": True,
        }
        if ac:
            items["kSecAttrAccessControl"] = ac
        st = SecItemAdd(_make_query(items), None)
        print(f"[E] SecItemAdd(dataProtection) -> {status_str(st)}", flush=True)
        results["E"] = {"add": int(st),
                        "is_missing_entitlement": int(st) == -34018,
                        "access_control_created": bool(ac)}
    except Exception as e:
        print(f"[E] FAILED: {type(e).__name__}: {e}", flush=True)
        results["E"] = {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# cleanup + verdict
# ---------------------------------------------------------------------------

def cleanup() -> None:
    _section("CLEANUP - deleting every __ttmt_vault_probe__ item")
    print("A residual prompt may appear here for a restrictive-ACL item - approve "
          "it so the throwaway item is removed.", flush=True)
    for account in ALL_ACCOUNTS:
        try:
            st = delete_generic(account)
            if int(st) not in (0, -25300):  # tolerate not-found
                print(f"[cleanup] delete({account}) -> {status_str(st)}", flush=True)
        except Exception as e:
            print(f"[cleanup] delete({account}) error: {e}", flush=True)
        # Also try the data-protection namespace (the Step E item, if it landed).
        try:
            delete_generic(account, data_protection=True)
        except Exception:
            pass
    # CLI sweep for anything left (e.g. the -A reference, or a stray duplicate).
    try:
        child_env = dict(os.environ)
        child_env["HOME"] = _REAL_HOME
        for _ in range(12):
            proc = subprocess.run(
                ["/usr/bin/security", "delete-generic-password", "-s", SERVICE, _KC_PATH],
                env=child_env, capture_output=True, text=True, timeout=20)
            if proc.returncode != 0:
                break
    except Exception as e:
        print(f"[cleanup] CLI sweep error: {e}", flush=True)
    # Verify nothing remains.
    try:
        proc = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", SERVICE, _KC_PATH],
            env={**os.environ, "HOME": _REAL_HOME}, capture_output=True, text=True, timeout=20)
        remaining = proc.returncode == 0
        print(f"[cleanup] residual __ttmt_vault_probe__ item present after cleanup: "
              f"{remaining}", flush=True)
    except Exception:
        pass
    try:
        # Drop the throwaway HOME/config tmp dir.
        import shutil
        shutil.rmtree(_ISO_DIR, ignore_errors=True)
    except Exception:
        pass


def verdict(results: dict) -> None:
    _section("VERDICT")
    print("(Structural hints from the ACL dumps. The AUTHORITATIVE verdict is the "
          "operator's Keychain Access wording + observed prompt count.)\n", flush=True)

    def _aa(entry):
        return entry.get("allow_all") if isinstance(entry, dict) else None

    for label in ("A1", "A2", "A3"):
        e = results.get(label, {})
        print(f"  {label}: add={status_str(e.get('add', 0)) if 'add' in e else e.get('error','?')} "
              f"allow_all(decrypt-ACL)={_aa(e)}", flush=True)
    ref = results.get("ref", {})
    print(f"  reference(-A): allow_all(decrypt-ACL)={_aa(ref)} "
          f"(this is the KNOWN allow-all shape to diff against)", flush=True)

    c = results.get("C", {})
    for label in ("A1", "A2", "A3", "ref"):
        ce = c.get(label, {})
        if "error" in ce:
            print(f"  C/{label}: {ce['error']}", flush=True)
        elif ce:
            print(f"  C/{label}: reads={status_str(ce['read1'])},{status_str(ce['read2'])},"
                  f"{status_str(ce['read3'])} update={status_str(ce['update'])} "
                  f"allow_all_after_update={ce.get('allow_all_after_update')}", flush=True)

    d = results.get("D", {})
    print(f"  D (LocalAuthentication): {d}", flush=True)

    e = results.get("E", {})
    if isinstance(e, dict) and "add" in e:
        print(f"  E (data-protection): status={status_str(e['add'])} "
              f"missing_entitlement={e.get('is_missing_entitlement')}", flush=True)
    else:
        print(f"  E (data-protection): {e}", flush=True)

    winners = [lbl for lbl in ("A3", "A1", "A2") if _aa(results.get(lbl, {})) is True]
    print("", flush=True)
    if winners:
        recipe = {
            "A3": "A3 = SecAccessCreate(NULL) + SecACLSetContents(NULL app list) on "
                  "each ACL, added via SecItemAdd(kSecAttrAccess=access)",
            "A1": "A1 = SecAccessCreate(NULL trusted list) added via "
                  "SecItemAdd(kSecAttrAccess=access)",
            "A2": "A2 = SecAccessCreate(empty trusted CFArray) added via "
                  "SecItemAdd(kSecAttrAccess=access)",
        }[winners[0]]
        print(f"  PRODUCTION ALLOW-ALL RECIPE (structural): {recipe}", flush=True)
        if len(winners) > 1:
            print(f"  (Also structurally allow-all: {', '.join(winners[1:])} - "
                  "operator confirms which fires zero prompts.)", flush=True)
        print("  CONFIRM by matching the reference-baseline ACL shape AND observing "
              "zero prompts on read/update in Step C + Keychain Access.", flush=True)
    else:
        print("  NO construction produced a structural allow-all decrypt ACL. If the "
              "operator ALSO sees prompts on every read, the design's ad-hoc "
              "allow-all premise is in doubt -> STOP and escalate (fallback: a single "
              "'Always Allow' item, or an encrypted-file vault keyed by one item).",
              flush=True)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    print("[cp-vault-acl] macOS credential vault allow-all ACL probe", flush=True)
    print(f"[cp-vault-acl] macos={platform.mac_ver()[0]} python={platform.python_version()}",
          flush=True)
    print(f"[cp-vault-acl] HOME/TTMT_CONFIG_DIR isolated -> {_ISO_DIR}", flush=True)
    print(f"[cp-vault-acl] real user home (keychain target) -> {_REAL_HOME}", flush=True)
    print(f"[cp-vault-acl] throwaway service = {SERVICE}", flush=True)

    if sys.platform != "darwin":
        print("[cp-vault-acl] FATAL: this probe is macOS-only.", flush=True)
        return 1

    if not _open_login_keychain():
        print("[cp-vault-acl] WARNING: could not open the real login keychain; "
              "operations fall back to the default search list, which under the "
              "HOME override may be the tmp keychain. Results may be unreliable.",
              flush=True)

    results = {}
    try:
        for step in (step_a, step_b, step_c, step_d, step_e):
            try:
                step(results)
            except KeyboardInterrupt:
                print(f"\n[cp-vault-acl] interrupted during {step.__name__}; "
                      "proceeding to cleanup.", flush=True)
                break
            except Exception as e:
                print(f"[cp-vault-acl] {step.__name__} crashed: "
                      f"{type(e).__name__}: {e}", flush=True)
    finally:
        try:
            verdict(results)
        except Exception as e:
            print(f"[cp-vault-acl] verdict failed: {e}", flush=True)
        cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
