import { initializeApp, getApps } from "firebase/app";
import {
  GoogleAuthProvider,
  createUserWithEmailAndPassword,
  getAuth,
  onAuthStateChanged,
  sendEmailVerification,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  updateProfile,
} from "firebase/auth";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

export const firebaseEnabled = Boolean(
  firebaseConfig.apiKey &&
    firebaseConfig.authDomain,
);

let auth = null;
if (firebaseEnabled) {
  const app = getApps().length ? getApps()[0] : initializeApp(firebaseConfig);
  auth = getAuth(app);
}

function toSession(user) {
  return {
    email: user.email || "",
    name: user.displayName || (user.email || "").split("@")[0] || "User",
  };
}

export function observeFirebaseSession(cb) {
  if (!auth) return () => {};
  return onAuthStateChanged(auth, (user) => {
    if (!user) return cb(null);
    const providerId = user.providerData?.[0]?.providerId;
    const requiresVerification = providerId === "password";
    if (requiresVerification && !user.emailVerified) return cb(null);
    cb(toSession(user));
  });
}

export async function firebaseLogin(email, password) {
  if (!auth) throw new Error("Firebase auth is not configured.");
  const cred = await signInWithEmailAndPassword(auth, email, password);
  if (!cred.user.emailVerified) {
    await signOut(auth);
    throw new Error("Please verify your email before signing in.");
  }
  return toSession(cred.user);
}

export async function firebaseSignup({ name, email, password }) {
  if (!auth) throw new Error("Firebase auth is not configured.");
  const cred = await createUserWithEmailAndPassword(auth, email, password);
  if (name?.trim()) {
    await updateProfile(cred.user, { displayName: name.trim() });
  }
  await sendEmailVerification(cred.user);
  await signOut(auth);
  return {
    emailVerificationSent: true,
    email,
  };
}

export async function firebaseLoginWithGoogle() {
  if (!auth) throw new Error("Firebase auth is not configured.");
  const provider = new GoogleAuthProvider();
  const cred = await signInWithPopup(auth, provider);
  return toSession(cred.user);
}

export async function firebaseLogout() {
  if (!auth) return;
  await signOut(auth);
}

export async function firebaseUpdateProfileName(name) {
  if (!auth?.currentUser) return null;
  const finalName = (name || "").trim();
  if (!finalName) return toSession(auth.currentUser);
  await updateProfile(auth.currentUser, { displayName: finalName });
  return toSession(auth.currentUser);
}

