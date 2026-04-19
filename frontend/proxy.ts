import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// For local development - make all routes public
const isPublicRoute = createRouteMatcher(["/(.*)"]);

export default clerkMiddleware(async (auth, request) => {
  // Skip auth protection for local development
  // if (!isPublicRoute(request)) {
  //   await auth.protect();
  // }
});

export const config = {
  // Exclude API routes and static files from middleware
  matcher: ["/((?!.+\\.[\\w]+$|_next|api).*)", "/"],
};
