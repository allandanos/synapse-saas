// hello-saas (Go) — Projects gauge through the framework API.
//
// The client-side variant of examples/python/hello-saas: create projects
// until the plan's cap trips (typed 402), then read the meters.
//
//	SYNAPSE_API (default http://localhost:8000)
//	SYNAPSE_TOKEN (access token), SYNAPSE_ORG (org uuid)
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
	orgID := os.Getenv("SYNAPSE_ORG")
	if token == "" {
		log.Fatal("Set SYNAPSE_TOKEN and SYNAPSE_ORG (login via the console first)")
	}

	client, err := synapse.New(api, synapse.Options{AccessToken: token, OrgID: orgID})
	if err != nil {
		log.Fatal(err)
	}
	ctx := context.Background()

	// Where we stand: plan + project cap
	snapshot, _ := client.Subscription().Current(ctx)
	if ent, ok := snapshot["entitlements"].(map[string]any); ok {
		fmt.Printf("plan=%v\n", ent["plan_key"])
		if limits, ok := ent["limits"].(map[string]any); ok {
			if projects, ok := limits["projects"].(map[string]any); ok {
				fmt.Printf("project cap=%v\n", projects["value"])
			}
		}
	}

	// Create projects until the plan says stop
	created := 0
	for i := 1; i <= 10; i++ {
		if _, err := client.Usage().Consume(ctx, "projects", 1); err != nil {
			var limitErr *synapse.LimitError
			if errors.As(err, &limitErr) {
				fmt.Printf("project %d: blocked — %s=%v (upgrade prompt)\n",
					i, limitErr.Metric(), limitErr.Body["limit"])
				break
			}
			log.Fatal(err)
		}
		created++
		fmt.Printf("project %d: created (+1 gauge meter)\n", i)
	}

	// Meters
	summary, _ := client.Usage().Summary(ctx)
	if metrics, ok := summary["metrics"].([]any); ok {
		for _, m := range metrics {
			if mm, ok := m.(map[string]any); ok {
				fmt.Printf("  %-12s used=%v limit=%v\n", mm["metric"], mm["used"], mm["limit"])
			}
		}
	}
	fmt.Printf("done — %d projects this run\n", created)
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
