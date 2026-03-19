import { supabase } from "./db";

type MemberRole = "admin" | "member" | "viewer";

interface InviteResult {
  success: boolean;
  role: MemberRole;
}

export async function inviteMember(
  orgId: string,
  email: string,
  role: MemberRole
): Promise<InviteResult> {
  try {
    const { data, error } = await supabase
      .from("org_members")
      .insert({ org_id: orgId, email, role });

    if (error) {
      // Database unique constraint violation
      if (error.code === "23505") {
        throw new Error("Member already exists in this organization");
      }
      // Foreign key violation
      if (error.code === "23503") {
        throw new Error("Organization does not exist");
      }
      throw error;
    }

    return { success: true, role };
  } catch (err) {
    throw err;
  }
}

export function getRoleLabel(role: MemberRole): string {
  switch (role) {
    case "admin":
      return "Administrator";
    case "member":
      return "Member";
    case "viewer":
      return "Viewer";
  }
}
