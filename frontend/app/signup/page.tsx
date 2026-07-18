import { redirect } from "next/navigation";

// Self-serve signup is disabled — the dashboard is invite/admin-provisioned
// (see scripts/create_dashboard_user.py). Any hit to /signup goes to sign-in.
export default function SignupPage() {
  redirect("/login");
}
