import { useState, useEffect, useCallback } from "react";
import { supabase } from "../lib/supabase";

// Demo identities for the access-control showcase. "Analyst" is just the
// anonymous (not-signed-in) session, which RLS limits to the public class.
// "Partner" is a pre-seeded account granted the confidential + restricted
// classes, so RLS reveals everything to it.
export const PARTNER_EMAIL = "partner@kibo.demo";
const PARTNER_PASSWORD = "kibo-partner";

export default function useAuth() {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  const identity = session?.user?.email === PARTNER_EMAIL ? "partner" : "analyst";

  const signInAsPartner = useCallback(async () => {
    if (!supabase) return;
    setLoading(true);
    try {
      await supabase.auth.signInWithPassword({ email: PARTNER_EMAIL, password: PARTNER_PASSWORD });
    } finally {
      setLoading(false);
    }
  }, []);

  const signOutToAnalyst = useCallback(async () => {
    if (!supabase) return;
    setLoading(true);
    try {
      await supabase.auth.signOut();
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    session,
    identity,
    email: session?.user?.email || null,
    loading,
    signInAsPartner,
    signOutToAnalyst,
  };
}
