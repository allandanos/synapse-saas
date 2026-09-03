// ai-saas example — Go SDK.
//
// A metered inference call: tokens consumed against the org's plan, quota
// breaches as typed errors you can bill around.
//
//	SYNAPSE_API (default http://localhost:8000)
//	SYNAPSE_KEY (an API key for the org)
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
	key := os.Getenv("SYNAPSE_KEY")
	if key == "" {
		log.Fatal("Set SYNAPSE_KEY to an org API key")
	}

	client, err := synapse.New(api, synapse.Options{APIKey: key})
	if err != nil {
		log.Fatal(err)
	}
	ctx := context.Background()

	// Where we stand: current quota + entitlements in one call
	snapshot, _ := client.Subscription().Current(ctx)
	if entitlements, ok := snapshot["entitlements"].(map[string]any); ok {
		fmt.Printf("plan=%v features=%v\n", entitlements["plan_key"], entitlements["features"])
	}

	// The metered inference call — tokens consumed atomically server-side.
	// In a real product this wraps your model invocation and meters its usage.
	const tokensPerCall = 25_000
	call := func() error {
		_, err := client.Usage().Consume(ctx, "ai_tokens", tokensPerCall)
		return err
	}

	for i := 1; i <= 10; i++ {
		if err := call(); err != nil {
			var limitErr *synapse.LimitError
			if errors.As(err, &limitErr) {
				fmt.Printf("call %d: quota wall — %s=%d (upgrade or bill overage)\n",
					i, limitErr.Metric(), limitErr.Body["limit"])
				return
			}
			log.Fatal(err)
		}
		fmt.Printf("call %d: +%d tokens metered\n", i, tokensPerCall)
	}

	// api_requests meters automatically on every key-authenticated call —
	// the summary reflects both the explicit token metering and the traffic.
	summary, _ := client.Usage().Summary(ctx)
	if metrics, ok := summary["metrics"].([]any); ok {
		for _, m := range metrics {
			if mm, ok := m.(map[string]any); ok {
				fmt.Printf("  %-12s used=%v limit=%v\n", mm["metric"], mm["used"], mm["limit"])
			}
		}
	}
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
