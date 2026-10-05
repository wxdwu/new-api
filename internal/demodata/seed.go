package demodata

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/constant"
	"github.com/QuantumNous/new-api/model"
	"gorm.io/gorm"
)

const (
	SeedMarkerKey      = "LocalDemoSeedVersion"
	CurrentSeedVersion = "1"

	demoNodeName = "local-demo"
	demoBaseURL  = "http://127.0.0.1:9"
)

var ErrUnmarkedDatabaseNotEmpty = errors.New("refusing to seed a non-empty database without the local demo marker")

type Config struct {
	RootUsername string
	RootPassword string
	Now          time.Time
}

type Summary struct {
	Users       int
	Tokens      int
	Channels    int
	Models      int
	Abilities   int
	Logs        int
	QuotaRows   int
	MetricRows  int
	SeedVersion string
}

type demoUserSpec struct {
	Username    string
	DisplayName string
	Email       string
	Role        int
	Status      int
	Quota       int
	UsedQuota   int
	AffCode     string
}

type demoTokenSpec struct {
	Username       string
	Name           string
	Key            string
	Status         int
	RemainQuota    int
	UnlimitedQuota bool
	ExpiredTime    int64
}

type demoVendorSpec struct {
	Name        string
	Description string
	Icon        string
}

type demoModelSpec struct {
	Name        string
	Description string
	Vendor      string
	Icon        string
	Tags        string
	Endpoints   string
}

type demoChannelSpec struct {
	Name   string
	Type   int
	Key    string
	Models []string
}

func Seed(ctx context.Context, db *gorm.DB, logDB *gorm.DB, cfg Config) (Summary, error) {
	if db == nil || logDB == nil {
		return Summary{}, errors.New("main and log databases are required")
	}
	cfg.RootUsername = strings.TrimSpace(cfg.RootUsername)
	if cfg.RootUsername == "" || len(cfg.RootUsername) > model.UserNameMaxLength {
		return Summary{}, fmt.Errorf("root username must contain 1-%d characters", model.UserNameMaxLength)
	}
	if len(cfg.RootPassword) < 8 || len(cfg.RootPassword) > 20 {
		return Summary{}, errors.New("root password must contain 8-20 characters")
	}
	if cfg.Now.IsZero() {
		cfg.Now = time.Now()
	}

	mainDB := db.WithContext(ctx)
	marked, err := hasSeedMarker(mainDB)
	if err != nil {
		return Summary{}, err
	}
	if !marked {
		var userCount int64
		if err := mainDB.Unscoped().Model(&model.User{}).Count(&userCount).Error; err != nil {
			return Summary{}, err
		}
		if userCount > 0 {
			return Summary{}, ErrUnmarkedDatabaseNotEmpty
		}
	}

	passwordHash, err := common.Password2Hash(cfg.RootPassword)
	if err != nil {
		return Summary{}, err
	}

	var users map[string]model.User
	var tokens map[string]model.Token
	var channels map[string]model.Channel
	summary := Summary{SeedVersion: CurrentSeedVersion}
	err = mainDB.Transaction(func(tx *gorm.DB) error {
		if err := seedOptions(tx); err != nil {
			return err
		}
		if err := seedSetup(tx, cfg.Now); err != nil {
			return err
		}

		var seedErr error
		users, seedErr = seedUsers(tx, cfg, passwordHash)
		if seedErr != nil {
			return seedErr
		}
		summary.Users = len(users)

		tokens, seedErr = seedTokens(tx, cfg.Now, users)
		if seedErr != nil {
			return seedErr
		}
		summary.Tokens = len(tokens)

		vendors, seedErr := seedVendors(tx, cfg.Now)
		if seedErr != nil {
			return seedErr
		}
		summary.Models, seedErr = seedModels(tx, cfg.Now, vendors)
		if seedErr != nil {
			return seedErr
		}

		channels, summary.Abilities, seedErr = seedChannels(tx, cfg.Now)
		if seedErr != nil {
			return seedErr
		}
		summary.Channels = len(channels)

		summary.QuotaRows, seedErr = seedQuotaRows(tx, cfg.Now, users, tokens, channels)
		if seedErr != nil {
			return seedErr
		}
		summary.MetricRows, seedErr = seedMetricRows(tx, cfg.Now)
		if seedErr != nil {
			return seedErr
		}
		if db == logDB {
			summary.Logs, seedErr = seedLogs(tx, cfg.Now, users, tokens, channels)
			if seedErr != nil {
				return seedErr
			}
		}
		return upsertOption(tx, SeedMarkerKey, CurrentSeedVersion)
	})
	if err != nil {
		return Summary{}, err
	}

	if db != logDB {
		summary.Logs, err = seedLogs(logDB.WithContext(ctx), cfg.Now, users, tokens, channels)
		if err != nil {
			return Summary{}, err
		}
	}
	return summary, nil
}

func hasSeedMarker(db *gorm.DB) (bool, error) {
	var option model.Option
	err := db.Where(&model.Option{Key: SeedMarkerKey}).First(&option).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return true, nil
}

func seedOptions(tx *gorm.DB) error {
	options := map[string]string{
		"theme.frontend":          "default",
		"PasswordLoginEnabled":    "true",
		"PasswordRegisterEnabled": "false",
		"DataExportEnabled":       "true",
		"LogConsumeEnabled":       "true",
		"DemoSiteEnabled":         "false",
		"SelfUseModeEnabled":      "false",
		"GitHubOAuthEnabled":      "false",
		"LinuxDOOAuthEnabled":     "false",
		"TelegramOAuthEnabled":    "false",
		"WeChatAuthEnabled":       "false",
	}
	for key, value := range options {
		if err := upsertOption(tx, key, value); err != nil {
			return err
		}
	}
	return nil
}

func upsertOption(tx *gorm.DB, key string, value string) error {
	var option model.Option
	err := tx.Where(&model.Option{Key: key}).First(&option).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return tx.Create(&model.Option{Key: key, Value: value}).Error
	}
	if err != nil {
		return err
	}
	return tx.Model(&model.Option{}).Where(&model.Option{Key: key}).Update("value", value).Error
}

func seedSetup(tx *gorm.DB, now time.Time) error {
	var setup model.Setup
	err := tx.First(&setup).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return tx.Create(&model.Setup{Version: common.Version, InitializedAt: now.Unix()}).Error
	}
	if err != nil {
		return err
	}
	return tx.Model(&model.Setup{}).Where("id = ?", setup.ID).Updates(map[string]any{
		"version":        common.Version,
		"initialized_at": now.Unix(),
	}).Error
}

func seedUsers(tx *gorm.DB, cfg Config, passwordHash string) (map[string]model.User, error) {
	specs := []demoUserSpec{
		{cfg.RootUsername, "Local Demo Root", "demo-root@local.invalid", common.RoleRootUser, common.UserStatusEnabled, 100000000, 1250000, "demo-root-aff"},
		{"demo-admin", "Local Demo Admin", "demo-admin@local.invalid", common.RoleAdminUser, common.UserStatusEnabled, 50000000, 820000, "demo-admin-aff"},
		{"demo-user", "Local Demo User", "demo-user@local.invalid", common.RoleCommonUser, common.UserStatusEnabled, 10000000, 360000, "demo-user-aff"},
		{"demo-disabled", "Disabled Demo User", "demo-disabled@local.invalid", common.RoleCommonUser, common.UserStatusDisabled, 5000000, 90000, "demo-disabled-aff"},
	}
	result := make(map[string]model.User, len(specs))
	for _, spec := range specs {
		var user model.User
		err := tx.Unscoped().Where("username = ?", spec.Username).First(&user).Error
		values := map[string]any{
			"password":      passwordHash,
			"display_name":  spec.DisplayName,
			"role":          spec.Role,
			"status":        spec.Status,
			"email":         spec.Email,
			"quota":         spec.Quota,
			"used_quota":    spec.UsedQuota,
			"request_count": 42,
			"group":         "default",
			"aff_code":      spec.AffCode,
			"setting":       "{}",
			"remark":        "Local demo fixture; not for production use",
			"deleted_at":    nil,
		}
		if errors.Is(err, gorm.ErrRecordNotFound) {
			user = model.User{
				Username:     spec.Username,
				Password:     passwordHash,
				DisplayName:  spec.DisplayName,
				Role:         spec.Role,
				Status:       spec.Status,
				Email:        spec.Email,
				Quota:        spec.Quota,
				UsedQuota:    spec.UsedQuota,
				RequestCount: 42,
				Group:        "default",
				AffCode:      spec.AffCode,
				Setting:      "{}",
				Remark:       "Local demo fixture; not for production use",
				CreatedAt:    cfg.Now.Unix(),
			}
			if err := tx.Create(&user).Error; err != nil {
				return nil, err
			}
		} else if err != nil {
			return nil, err
		} else {
			if err := tx.Unscoped().Model(&model.User{}).Where("id = ?", user.Id).Updates(values).Error; err != nil {
				return nil, err
			}
			if err := tx.Unscoped().First(&user, user.Id).Error; err != nil {
				return nil, err
			}
		}
		result[spec.Username] = user
	}
	return result, nil
}

func seedTokens(tx *gorm.DB, now time.Time, users map[string]model.User) (map[string]model.Token, error) {
	specs := []demoTokenSpec{
		{"demo-root", "Demo unlimited token", "local-demo-root-unlimited", common.TokenStatusEnabled, 0, true, -1},
		{"demo-root", "Demo limited token", "local-demo-root-limited", common.TokenStatusEnabled, 500000, false, -1},
		{"demo-root", "Demo expired token", "local-demo-root-expired", common.TokenStatusExpired, 100000, false, now.Add(-time.Hour).Unix()},
		{"demo-root", "Demo disabled token", "local-demo-root-disabled", common.TokenStatusDisabled, 100000, false, -1},
		{"demo-admin", "Demo admin token", "local-demo-admin-token", common.TokenStatusEnabled, 2000000, false, -1},
		{"demo-user", "Demo user token", "local-demo-user-token", common.TokenStatusEnabled, 500000, false, -1},
	}
	keys := make([]string, 0, len(specs))
	for _, spec := range specs {
		keys = append(keys, spec.Key)
	}
	if err := tx.Unscoped().Where(map[string]any{"key": keys}).Delete(&model.Token{}).Error; err != nil {
		return nil, err
	}

	result := make(map[string]model.Token, len(specs))
	for _, spec := range specs {
		user, ok := users[spec.Username]
		if !ok && spec.Username == "demo-root" {
			for _, candidate := range users {
				if candidate.Role == common.RoleRootUser {
					user = candidate
					ok = true
					break
				}
			}
		}
		if !ok {
			return nil, fmt.Errorf("demo user %q is missing", spec.Username)
		}
		token := model.Token{
			UserId:         user.Id,
			Key:            spec.Key,
			Status:         spec.Status,
			Name:           spec.Name,
			CreatedTime:    now.Add(-7 * 24 * time.Hour).Unix(),
			AccessedTime:   now.Add(-time.Hour).Unix(),
			ExpiredTime:    spec.ExpiredTime,
			RemainQuota:    spec.RemainQuota,
			UnlimitedQuota: spec.UnlimitedQuota,
			Group:          "default",
		}
		if err := tx.Create(&token).Error; err != nil {
			return nil, err
		}
		result[spec.Key] = token
	}
	return result, nil
}

func seedVendors(tx *gorm.DB, now time.Time) (map[string]model.Vendor, error) {
	specs := []demoVendorSpec{
		{"Local Demo OpenAI", "Disconnected OpenAI-compatible demo vendor", "OpenAI"},
		{"Local Demo Anthropic", "Disconnected Anthropic-compatible demo vendor", "Anthropic"},
		{"Local Demo Gemini", "Disconnected Gemini-compatible demo vendor", "Gemini"},
	}
	result := make(map[string]model.Vendor, len(specs))
	for _, spec := range specs {
		var vendor model.Vendor
		err := tx.Where("name = ?", spec.Name).First(&vendor).Error
		if errors.Is(err, gorm.ErrRecordNotFound) {
			vendor = model.Vendor{Name: spec.Name, Description: spec.Description, Icon: spec.Icon, Status: 1, CreatedTime: now.Unix(), UpdatedTime: now.Unix()}
			if err := tx.Create(&vendor).Error; err != nil {
				return nil, err
			}
		} else if err != nil {
			return nil, err
		} else if err := tx.Model(&model.Vendor{}).Where("id = ?", vendor.Id).Updates(map[string]any{
			"description":  spec.Description,
			"icon":         spec.Icon,
			"status":       1,
			"updated_time": now.Unix(),
		}).Error; err != nil {
			return nil, err
		}
		result[spec.Name] = vendor
	}
	return result, nil
}

func demoModelSpecs() []demoModelSpec {
	return []demoModelSpec{
		{"local-demo-gpt-4.1-mini", "Local-only chat model metadata", "Local Demo OpenAI", "OpenAI", "demo,chat", `["/v1/chat/completions"]`},
		{"local-demo-text-embedding-3-small", "Local-only embedding model metadata", "Local Demo OpenAI", "OpenAI", "demo,embedding", `["/v1/embeddings"]`},
		{"local-demo-claude-3.5-haiku", "Local-only messages model metadata", "Local Demo Anthropic", "Anthropic", "demo,chat", `["/v1/messages"]`},
		{"local-demo-gemini-2.0-flash", "Local-only Gemini model metadata", "Local Demo Gemini", "Gemini", "demo,chat", `["/v1beta/models"]`},
	}
}

func seedModels(tx *gorm.DB, now time.Time, vendors map[string]model.Vendor) (int, error) {
	for _, spec := range demoModelSpecs() {
		vendor, ok := vendors[spec.Vendor]
		if !ok {
			return 0, fmt.Errorf("demo vendor %q is missing", spec.Vendor)
		}
		var metadata model.Model
		err := tx.Where("model_name = ?", spec.Name).First(&metadata).Error
		values := map[string]any{
			"description":   spec.Description,
			"icon":          spec.Icon,
			"tags":          spec.Tags,
			"vendor_id":     vendor.Id,
			"endpoints":     spec.Endpoints,
			"status":        1,
			"sync_official": 0,
			"name_rule":     model.NameRuleExact,
			"updated_time":  now.Unix(),
		}
		if errors.Is(err, gorm.ErrRecordNotFound) {
			metadata = model.Model{ModelName: spec.Name, Description: spec.Description, Icon: spec.Icon, Tags: spec.Tags, VendorID: vendor.Id, Endpoints: spec.Endpoints, Status: 1, SyncOfficial: 0, NameRule: model.NameRuleExact, CreatedTime: now.Unix(), UpdatedTime: now.Unix()}
			if err := tx.Create(&metadata).Error; err != nil {
				return 0, err
			}
		} else if err != nil {
			return 0, err
		} else if err := tx.Model(&model.Model{}).Where("id = ?", metadata.Id).Updates(values).Error; err != nil {
			return 0, err
		}
	}
	return len(demoModelSpecs()), nil
}

func demoChannelSpecs() []demoChannelSpec {
	return []demoChannelSpec{
		{"Local Demo OpenAI (disconnected)", constant.ChannelTypeOpenAI, "local-demo-openai-disabled", []string{"local-demo-gpt-4.1-mini", "local-demo-text-embedding-3-small"}},
		{"Local Demo Anthropic (disconnected)", constant.ChannelTypeAnthropic, "local-demo-anthropic-disabled", []string{"local-demo-claude-3.5-haiku"}},
		{"Local Demo Gemini (disconnected)", constant.ChannelTypeGemini, "local-demo-gemini-disabled", []string{"local-demo-gemini-2.0-flash"}},
	}
}

func seedChannels(tx *gorm.DB, now time.Time) (map[string]model.Channel, int, error) {
	result := make(map[string]model.Channel, len(demoChannelSpecs()))
	abilityCount := 0
	for _, spec := range demoChannelSpecs() {
		models := strings.Join(spec.Models, ",")
		var channel model.Channel
		err := tx.Where("name = ?", spec.Name).First(&channel).Error
		weight := uint(0)
		priority := int64(0)
		autoBan := 0
		baseURL := demoBaseURL
		remark := "Local demo fixture; upstream calls are intentionally disabled"
		values := map[string]any{
			"type":     spec.Type,
			"key":      spec.Key,
			"status":   common.ChannelStatusManuallyDisabled,
			"weight":   weight,
			"base_url": baseURL,
			"models":   models,
			"group":    "default",
			"priority": priority,
			"auto_ban": autoBan,
			"remark":   remark,
		}
		if errors.Is(err, gorm.ErrRecordNotFound) {
			channel = model.Channel{
				Type:        spec.Type,
				Key:         spec.Key,
				Status:      common.ChannelStatusManuallyDisabled,
				Name:        spec.Name,
				Weight:      &weight,
				CreatedTime: now.Unix(),
				BaseURL:     &baseURL,
				Models:      models,
				Group:       "default",
				Priority:    &priority,
				AutoBan:     &autoBan,
				Remark:      &remark,
			}
			if err := tx.Create(&channel).Error; err != nil {
				return nil, 0, err
			}
		} else if err != nil {
			return nil, 0, err
		} else {
			if err := tx.Model(&model.Channel{}).Where("id = ?", channel.Id).Updates(values).Error; err != nil {
				return nil, 0, err
			}
			if err := tx.First(&channel, channel.Id).Error; err != nil {
				return nil, 0, err
			}
		}
		if err := tx.Where("channel_id = ?", channel.Id).Delete(&model.Ability{}).Error; err != nil {
			return nil, 0, err
		}
		for _, modelName := range spec.Models {
			ability := model.Ability{Group: "default", Model: modelName, ChannelId: channel.Id, Enabled: false, Priority: &priority, Weight: weight}
			if err := tx.Create(&ability).Error; err != nil {
				return nil, 0, err
			}
			abilityCount++
		}
		result[spec.Name] = channel
	}
	return result, abilityCount, nil
}

func seedQuotaRows(tx *gorm.DB, now time.Time, users map[string]model.User, tokens map[string]model.Token, channels map[string]model.Channel) (int, error) {
	if err := tx.Where("node_name = ?", demoNodeName).Delete(&model.QuotaData{}).Error; err != nil {
		return 0, err
	}
	root := findRootUser(users)
	openAI := channels["Local Demo OpenAI (disconnected)"]
	anthropic := channels["Local Demo Anthropic (disconnected)"]
	gemini := channels["Local Demo Gemini (disconnected)"]
	rows := make([]model.QuotaData, 0, 28)
	for day := 0; day < 7; day++ {
		bucket := now.Add(-time.Duration(day) * 24 * time.Hour).Unix()
		bucket -= bucket % 3600
		rows = append(rows,
			model.QuotaData{UserID: root.Id, Username: root.Username, ModelName: "local-demo-gpt-4.1-mini", CreatedAt: bucket, UseGroup: "default", TokenID: tokens["local-demo-root-unlimited"].Id, ChannelID: openAI.Id, NodeName: demoNodeName, TokenUsed: 1200 + day*35, Count: 5 + day, Quota: 2400 + day*80},
			model.QuotaData{UserID: users["demo-admin"].Id, Username: "demo-admin", ModelName: "local-demo-claude-3.5-haiku", CreatedAt: bucket, UseGroup: "default", TokenID: tokens["local-demo-admin-token"].Id, ChannelID: anthropic.Id, NodeName: demoNodeName, TokenUsed: 900 + day*20, Count: 4 + day, Quota: 1800 + day*60},
			model.QuotaData{UserID: users["demo-user"].Id, Username: "demo-user", ModelName: "local-demo-gemini-2.0-flash", CreatedAt: bucket, UseGroup: "default", TokenID: tokens["local-demo-user-token"].Id, ChannelID: gemini.Id, NodeName: demoNodeName, TokenUsed: 650 + day*15, Count: 3 + day, Quota: 1300 + day*40},
			model.QuotaData{UserID: users["demo-user"].Id, Username: "demo-user", ModelName: "local-demo-text-embedding-3-small", CreatedAt: bucket, UseGroup: "default", TokenID: tokens["local-demo-user-token"].Id, ChannelID: openAI.Id, NodeName: demoNodeName, TokenUsed: 1800 + day*50, Count: 8 + day, Quota: 700 + day*25},
		)
	}
	if err := tx.Create(&rows).Error; err != nil {
		return 0, err
	}
	return len(rows), nil
}

func seedMetricRows(tx *gorm.DB, now time.Time) (int, error) {
	modelNames := []string{"local-demo-gpt-4.1-mini", "local-demo-claude-3.5-haiku", "local-demo-gemini-2.0-flash"}
	if err := tx.Where("model_name IN ?", modelNames).
		Where(&model.PerfMetric{Group: "default"}).
		Delete(&model.PerfMetric{}).Error; err != nil {
		return 0, err
	}
	rows := make([]model.PerfMetric, 0, 21)
	for day := 0; day < 7; day++ {
		bucket := now.Add(-time.Duration(day) * 24 * time.Hour).Unix()
		bucket -= bucket % 3600
		for index, modelName := range modelNames {
			requests := int64(12 + day + index*3)
			rows = append(rows, model.PerfMetric{
				ModelName:      modelName,
				Group:          "default",
				BucketTs:       bucket,
				RequestCount:   requests,
				SuccessCount:   requests - 1,
				TotalLatencyMs: requests * int64(650+index*120),
				TtftSumMs:      requests * int64(180+index*30),
				TtftCount:      requests,
				OutputTokens:   requests * int64(220+index*40),
				GenerationMs:   requests * int64(520+index*80),
			})
		}
	}
	if err := tx.Create(&rows).Error; err != nil {
		return 0, err
	}
	return len(rows), nil
}

func seedLogs(db *gorm.DB, now time.Time, users map[string]model.User, tokens map[string]model.Token, channels map[string]model.Channel) (int, error) {
	requestIDs := make([]string, 0, 14)
	for index := 0; index < 14; index++ {
		requestIDs = append(requestIDs, fmt.Sprintf("local-demo-log-%02d", index+1))
	}
	if err := db.Where("request_id IN ?", requestIDs).Delete(&model.Log{}).Error; err != nil {
		return 0, err
	}
	root := findRootUser(users)
	openAI := channels["Local Demo OpenAI (disconnected)"]
	anthropic := channels["Local Demo Anthropic (disconnected)"]
	gemini := channels["Local Demo Gemini (disconnected)"]
	consumeUsers := []model.User{root, users["demo-admin"], users["demo-user"]}
	consumeTokens := []model.Token{tokens["local-demo-root-unlimited"], tokens["local-demo-admin-token"], tokens["local-demo-user-token"]}
	consumeChannels := []model.Channel{openAI, anthropic, gemini}
	consumeModels := []string{"local-demo-gpt-4.1-mini", "local-demo-claude-3.5-haiku", "local-demo-gemini-2.0-flash"}
	rows := make([]model.Log, 0, 14)
	for day := 0; day < 7; day++ {
		index := day % len(consumeUsers)
		createdAt := now.Add(-time.Duration(day) * 24 * time.Hour).Unix()
		rows = append(rows, model.Log{
			UserId:           consumeUsers[index].Id,
			CreatedAt:        createdAt,
			Type:             model.LogTypeConsume,
			Content:          "Local demo usage record",
			Username:         consumeUsers[index].Username,
			TokenName:        consumeTokens[index].Name,
			ModelName:        consumeModels[index],
			Quota:            1200 + day*90,
			PromptTokens:     600 + day*25,
			CompletionTokens: 180 + day*10,
			UseTime:          720 + day*30,
			ChannelId:        consumeChannels[index].Id,
			TokenId:          consumeTokens[index].Id,
			Group:            "default",
			Ip:               "127.0.0.1",
			RequestId:        requestIDs[day*2],
			Other:            common.MapToJsonStr(map[string]any{"demo": true, "node_name": demoNodeName}),
		})
		secondaryType := []int{model.LogTypeLogin, model.LogTypeManage, model.LogTypeError}[day%3]
		rows = append(rows, model.Log{
			UserId:    root.Id,
			CreatedAt: createdAt - 1800,
			Type:      secondaryType,
			Content:   "Local demo operational record",
			Username:  root.Username,
			Group:     "default",
			Ip:        "127.0.0.1",
			RequestId: requestIDs[day*2+1],
			Other:     common.MapToJsonStr(map[string]any{"demo": true, "node_name": demoNodeName}),
		})
	}
	if err := db.Create(&rows).Error; err != nil {
		return 0, err
	}
	return len(rows), nil
}

func findRootUser(users map[string]model.User) model.User {
	for _, user := range users {
		if user.Role == common.RoleRootUser {
			return user
		}
	}
	return model.User{}
}
