package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/internal/demodata"
	"github.com/QuantumNous/new-api/logger"
	"github.com/QuantumNous/new-api/model"
	"github.com/QuantumNous/new-api/service/authz"
	"github.com/QuantumNous/new-api/setting/ratio_setting"
	"github.com/joho/godotenv"
)

const (
	defaultRootUsername = "demo-root"
	defaultRootPassword = "LocalDemo123!"
)

var errDemoSeedNotEnabled = errors.New("local demo seeding is disabled; set LOCAL_DEMO_SEED=1 to confirm this is an isolated local database")

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "local demo seed failed:", err)
		os.Exit(1)
	}
}

func run() error {
	_ = godotenv.Load(".env")
	cfg, err := configFromEnv(os.Getenv)
	if err != nil {
		return err
	}

	common.InitEnv()
	logger.SetupLogger()
	ratio_setting.InitRatioSettings()
	if err := model.InitDB(); err != nil {
		return fmt.Errorf("initialize main database: %w", err)
	}
	if err := model.InitLogDB(); err != nil {
		_ = model.CloseDB()
		return fmt.Errorf("initialize log database: %w", err)
	}
	defer func() {
		if err := model.CloseDB(); err != nil {
			common.SysError("close local demo database: " + err.Error())
		}
	}()

	if err := authz.Init(model.DB); err != nil {
		return fmt.Errorf("initialize authorization data: %w", err)
	}
	summary, err := demodata.Seed(context.Background(), model.DB, model.LOG_DB, cfg)
	if err != nil {
		return err
	}
	fmt.Printf(
		"local demo data ready: users=%d tokens=%d channels=%d models=%d logs=%d quota_rows=%d metric_rows=%d seed_version=%s root_username=%s\n",
		summary.Users,
		summary.Tokens,
		summary.Channels,
		summary.Models,
		summary.Logs,
		summary.QuotaRows,
		summary.MetricRows,
		summary.SeedVersion,
		cfg.RootUsername,
	)
	return nil
}

func configFromEnv(getenv func(string) string) (demodata.Config, error) {
	if strings.TrimSpace(getenv("LOCAL_DEMO_SEED")) != "1" {
		return demodata.Config{}, errDemoSeedNotEnabled
	}
	password := getenv("LOCAL_DEMO_ROOT_PASSWORD")
	if password == "" {
		password = defaultRootPassword
	}
	return demodata.Config{RootUsername: defaultRootUsername, RootPassword: password}, nil
}
