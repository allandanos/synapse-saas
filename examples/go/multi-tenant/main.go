// multi-tenant (Go) — one user, two orgs, hard isolation.
//
//	SYNAPSE_API (default http://localhost:8000)
//	SYNAPSE_TOKEN (access token owning 2+ orgs)
package main

import (
	"context"
	"fmt"
	"log"
	"os"

	"github.com/allandanos/synapse-saas/sdk/go"
)

func main() {
	api := envOr("SYNAPSE_API", "http://localhost:8000")
	token := os.Getenv("SYNAPSE_TOKEN")
	if token == "" {
		log.Fatal("Set SYNAPSE_TOKEN to an access token owning two orgs")
	}

	me, err := synapse.New(api, synapse.Options{AccessToken: token})
	if err != nil {
		log.Fatal(err)
	}
	ctx := context.Background()

	profile, _ := me.Auth().Me(ctx)
	orgsAny, _ := profile["orgs"].([]any)
	if len(orgsAny) < 2 {
		log.Fatal("Create a second org for this user to see isolation in action")
	}
	orgA := orgsAny[0].(map[string]any)
	orgB := orgsAny[1].(map[string]any)
	fmt.Printf("user has %d orgs: %v, %v\n", len(orgsAny), orgA["slug"], orgB["slug"])

	clientA, _ := synapse.New(api, synapse.Options{AccessToken: token, OrgID: str(orgA["id"])})
	clientB, _ := synapse.New(api, synapse.Options{AccessToken: token, OrgID: str(orgB["id"])})

	// ── Usage is per-tenant ────────────────────────────────────────────────
	if _, err := clientA.Usage().Consume(ctx, "api_requests", 100); err != nil {
		log.Fatal(err)
	}
	summaryB, _ := clientB.Usage().Summary(ctx)
	printUsed("org A consumed 100; org B api_requests still at", summaryB)

	// ── Members are per-tenant ─────────────────────────────────────────────
	membersA, _ := clientA.Members().List(ctx)
	membersB, _ := clientB.Members().List(ctx)
	fmt.Printf("members — A: %d, B: %d\n", countData(membersA), countData(membersB))

	// ── Entitlements are per-tenant ────────────────────────────────────────
	entA, _ := clientA.Entitlements().Effective(ctx)
	entB, _ := clientB.Entitlements().Effective(ctx)
	fmt.Printf("plans — A: %v, B: %v\n", planKey(entA), planKey(entB))
}

func str(v any) string { s, _ := v.(string); return s }

func countData(list map[string]any) int {
	if d, ok := list["data"].([]any); ok {
		return len(d)
	}
	return 0
}

func planKey(ent map[string]any) any { return ent["plan_key"] }

func printUsed(prefix string, summary map[string]any) {
	used := 0.0
	if metrics, ok := summary["metrics"].([]any); ok {
		for _, m := range metrics {
			if mm, ok := m.(map[string]any); ok && mm["metric"] == "api_requests" {
				if u, ok := mm["used"].(float64); ok {
					used = u
				}
			}
		}
	}
	fmt.Printf("%s %.0f\n", prefix, used)
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
