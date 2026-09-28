// subscription (Go) — freemium lifecycle: quota wall → trial grant → upgrade.
//
//	SYNAPSE_API (default http://localhost:8000)
//	SYNAPSE_TOKEN (access token for an org owner), SYNAPSE_ORG (org uuid)
//	SYNAPSE_PLATFORM_TOKEN (optional: platform-admin token — grants are an operator action)
package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"os"

	"github.com/allandanos/synapse-saas/sdk/go"
)

func main() {
	api := envOr("SYNAPSE_API", "http://localhost:8000")
	token := os.Getenv("SYNAPSE_TOKEN")
	if token == "" {
		log.Fatal("Set SYNAPSE_TOKEN and SYNAPSE_ORG (login via the console first)")
	}
	client, err := synapse.New(api, synapse.Options{AccessToken: token, OrgID: os.Getenv("SYNAPSE_ORG")})
	if err != nil {
		log.Fatal(err)
	}
	ctx := context.Background()

	// ── Where we start: the free plan ──────────────────────────────────────
	start, _ := client.Subscription().Current(ctx)
	if ent, ok := start["entitlements"].(map[string]any); ok {
		fmt.Printf("plan=%v features=%v\n", ent["plan_key"], ent["features"])
	}

	// ── Hit the seat quota: typed 402 with hints ───────────────────────────
	for i := 0; i < 5; i++ {
		if _, err := client.Members().Invite(ctx, fmt.Sprintf("seat-%d@example.com", i)); err != nil {
			var limitErr *synapse.LimitError
			if errors.As(err, &limitErr) {
				fmt.Printf("quota wall: %s=%v → upgrade at %v\n",
					limitErr.Metric(), limitErr.Body["limit"], limitErr.Body["upgrade_url"])
				break
			}
			log.Fatal(err)
		}
	}

	// ── Trial grant: a paid feature without a plan change ──────────────────
	// Grants are an OPERATOR action: a tenant can never grant itself features.
	if platformToken := os.Getenv("SYNAPSE_PLATFORM_TOKEN"); platformToken != "" {
		operator, err := synapse.New(api, synapse.Options{AccessToken: platformToken})
		if err != nil {
			log.Fatal(err)
		}
		if _, err := operator.Entitlements().Grant(ctx, os.Getenv("SYNAPSE_ORG"), "advanced_reports", "promo", 14); err != nil {
			log.Fatal(err)
		}
	} else {
		fmt.Println("skipping trial grant (set SYNAPSE_PLATFORM_TOKEN — grants are an operator action)")
	}
	granted, _ := client.Entitlements().Effective(ctx)
	if ent, ok := granted["features"].([]any); ok {
		has := false
		for _, f := range ent {
			if f == "advanced_reports" {
				has = true
			}
		}
		fmt.Printf("after grant: advanced_reports=%v (plan unchanged)\n", has)
	}

	// ── Plan upgrade: the cap moves ─────────────────────────────────────────
	if _, err := client.Subscription().Change(ctx, "starter"); err != nil {
		log.Fatal(err)
	}
	after, _ := client.Subscription().Current(ctx)
	if ent, ok := after["entitlements"].(map[string]any); ok {
		fmt.Printf("after upgrade: plan=%v, seats=10 — invites pass now\n", ent["plan_key"])
	}
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
