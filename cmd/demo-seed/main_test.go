package main

import (
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestConfigFromEnvRequiresExplicitLocalDemoOptIn(t *testing.T) {
	_, err := configFromEnv(func(string) string { return "" })
	require.Error(t, err)
	assert.True(t, errors.Is(err, errDemoSeedNotEnabled))
}

func TestConfigFromEnvUsesSafeLocalDefaults(t *testing.T) {
	values := map[string]string{
		"LOCAL_DEMO_SEED": "1",
	}

	cfg, err := configFromEnv(func(key string) string { return values[key] })
	require.NoError(t, err)
	assert.Equal(t, "demo-root", cfg.RootUsername)
	assert.Equal(t, "LocalDemo123!", cfg.RootPassword)
}

func TestConfigFromEnvAllowsOnlyPasswordOverride(t *testing.T) {
	values := map[string]string{
		"LOCAL_DEMO_SEED":          "1",
		"LOCAL_DEMO_ROOT_USERNAME": "local-admin",
		"LOCAL_DEMO_ROOT_PASSWORD": "DifferentLocal123!",
	}

	cfg, err := configFromEnv(func(key string) string { return values[key] })
	require.NoError(t, err)
	assert.Equal(t, "demo-root", cfg.RootUsername)
	assert.Equal(t, "DifferentLocal123!", cfg.RootPassword)
}
