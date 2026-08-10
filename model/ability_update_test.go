package model

import (
	"os"
	"testing"
	"time"

	"github.com/QuantumNous/new-api/common"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/mysql"
	"gorm.io/gorm"
)

func TestChannelUpdatePreservesExistingAbilityTag(t *testing.T) {
	truncateTables(t)

	channel := Channel{
		Type:     1,
		Key:      "local-test-key",
		Status:   common.ChannelStatusEnabled,
		Name:     "before update",
		Models:   "gpt-test-model",
		Group:    "default",
		Priority: common.GetPointer[int64](0),
		Weight:   common.GetPointer[uint](0),
	}
	require.NoError(t, channel.Insert())

	require.NoError(t, DB.Model(&Ability{}).
		Where("channel_id = ?", channel.Id).
		Update("tag", "1").Error)

	channel.Name = "after update"
	require.NoError(t, channel.Update())

	var ability Ability
	require.NoError(t, DB.Where(
		"channel_id = ? AND `group` = ? AND model = ?",
		channel.Id,
		"default",
		"gpt-test-model",
	).First(&ability).Error)
	require.NotNil(t, ability.Tag)
	require.Equal(t, "1", *ability.Tag)
}

func TestChannelUpdateReconcilesModelsWithoutOverwritingExistingTags(t *testing.T) {
	truncateTables(t)

	channelTag := "channel-tag"
	channel := Channel{
		Type:     1,
		Key:      "local-test-key",
		Status:   common.ChannelStatusEnabled,
		Name:     "model reconciliation",
		Models:   "keep-model,remove-model",
		Group:    "default",
		Tag:      &channelTag,
		Priority: common.GetPointer[int64](0),
		Weight:   common.GetPointer[uint](0),
	}
	require.NoError(t, channel.Insert())
	require.NoError(t, DB.Model(&Ability{}).
		Where("channel_id = ? AND model = ?", channel.Id, "keep-model").
		Update("tag", "ability-tag").Error)

	channel.Models = "keep-model,new-model"
	require.NoError(t, channel.Update())

	var abilities []Ability
	require.NoError(t, DB.Where("channel_id = ?", channel.Id).
		Order("model").Find(&abilities).Error)
	require.Len(t, abilities, 2)
	require.Equal(t, "keep-model", abilities[0].Model)
	require.NotNil(t, abilities[0].Tag)
	require.Equal(t, "ability-tag", *abilities[0].Tag)
	require.Equal(t, "new-model", abilities[1].Model)
	require.Nil(t, abilities[1].Tag)
}

func TestChannelTagDoesNotOverwriteAbilityTags(t *testing.T) {
	truncateTables(t)

	channel := Channel{
		Type:     1,
		Key:      "local-test-key",
		Status:   common.ChannelStatusEnabled,
		Name:     "explicit tag update",
		Models:   "gpt-test-model",
		Group:    "default",
		Priority: common.GetPointer[int64](0),
		Weight:   common.GetPointer[uint](0),
	}
	require.NoError(t, channel.Insert())
	require.NoError(t, DB.Model(&Ability{}).
		Where("channel_id = ?", channel.Id).
		Update("tag", "ability-tag").Error)

	updatedTag := "updated-channel-tag"
	channel.Tag = &updatedTag
	require.NoError(t, channel.Update())

	var ability Ability
	require.NoError(t, DB.Where("channel_id = ?", channel.Id).First(&ability).Error)
	require.NotNil(t, ability.Tag)
	require.Equal(t, "ability-tag", *ability.Tag)
}

func TestChannelTagEnabledModelsControlsAbilityTags(t *testing.T) {
	truncateTables(t)

	channelTag := "internal-channel-tag"
	channel := Channel{
		Type:             1,
		Key:              "local-test-key",
		Status:           common.ChannelStatusEnabled,
		Name:             "tag enabled models",
		Models:           "enabled-model,disabled-model",
		Group:            "default",
		Tag:              &channelTag,
		TagEnabledModels: []string{"enabled-model"},
		Priority:         common.GetPointer[int64](0),
		Weight:           common.GetPointer[uint](0),
	}
	require.NoError(t, channel.Insert())

	var abilities []Ability
	require.NoError(t, DB.Where("channel_id = ?", channel.Id).Order("model").Find(&abilities).Error)
	require.Len(t, abilities, 2)
	require.Equal(t, "disabled-model", abilities[0].Model)
	require.Nil(t, abilities[0].Tag)
	require.Equal(t, "enabled-model", abilities[1].Model)
	require.NotNil(t, abilities[1].Tag)
	require.Equal(t, "1", *abilities[1].Tag)

	channel.TagEnabledModels = []string{"disabled-model"}
	require.NoError(t, channel.Update())

	require.NoError(t, DB.Where("channel_id = ?", channel.Id).Order("model").Find(&abilities).Error)
	require.Nil(t, abilities[1].Tag)
	require.NotNil(t, abilities[0].Tag)
	require.Equal(t, "1", *abilities[0].Tag)
}

func TestAbilityRebuildPathsPreserveTags(t *testing.T) {
	truncateTables(t)

	channel := Channel{
		Type:     1,
		Key:      "local-test-key",
		Status:   common.ChannelStatusEnabled,
		Name:     "ability rebuild",
		Models:   "enabled-model,custom-tag-model",
		Group:    "default",
		Priority: common.GetPointer[int64](0),
		Weight:   common.GetPointer[uint](0),
	}
	require.NoError(t, channel.Insert())
	require.NoError(t, DB.Model(&Ability{}).
		Where("channel_id = ? AND model = ?", channel.Id, "enabled-model").
		Update("tag", "1").Error)
	require.NoError(t, DB.Model(&Ability{}).
		Where("channel_id = ? AND model = ?", channel.Id, "custom-tag-model").
		Update("tag", "custom-tag").Error)

	require.NoError(t, channel.UpdateAbilities(nil))
	assertStoredAbilityTag(t, channel.Id, "enabled-model", "1")
	assertStoredAbilityTag(t, channel.Id, "custom-tag-model", "custom-tag")

	successCount, failCount, err := FixAbility()
	require.NoError(t, err)
	require.Equal(t, 1, successCount)
	require.Zero(t, failCount)
	assertStoredAbilityTag(t, channel.Id, "enabled-model", "1")
	assertStoredAbilityTag(t, channel.Id, "custom-tag-model", "custom-tag")
}

func TestChannelTagOperationsDoNotOverwriteAbilityTag(t *testing.T) {
	truncateTables(t)

	channelTag := "channel-batch-tag"
	channel := Channel{
		Type:             1,
		Key:              "local-test-key",
		Status:           common.ChannelStatusEnabled,
		Name:             "channel tag operations",
		Models:           "enabled-model",
		Group:            "default",
		Tag:              &channelTag,
		TagEnabledModels: []string{"enabled-model"},
		Priority:         common.GetPointer[int64](0),
		Weight:           common.GetPointer[uint](0),
	}
	require.NoError(t, channel.Insert())

	require.NoError(t, DisableChannelByTag(channelTag))
	var ability Ability
	require.NoError(t, DB.Where("channel_id = ?", channel.Id).First(&ability).Error)
	require.False(t, ability.Enabled)
	require.NotNil(t, ability.Tag)
	require.Equal(t, "1", *ability.Tag)

	require.NoError(t, EnableChannelByTag(channelTag))
	newChannelTag := "renamed-channel-batch-tag"
	priority := int64(9)
	require.NoError(t, EditChannelByTag(channelTag, &newChannelTag, nil, nil, nil, &priority, nil, nil, nil))
	require.NoError(t, DB.Where("channel_id = ?", channel.Id).First(&ability).Error)
	require.True(t, ability.Enabled)
	require.EqualValues(t, priority, *ability.Priority)
	require.NotNil(t, ability.Tag)
	require.Equal(t, "1", *ability.Tag)

	finalChannelTag := "final-channel-batch-tag"
	require.NoError(t, BatchSetChannelTag([]int{channel.Id}, &finalChannelTag))
	assertStoredAbilityTag(t, channel.Id, "enabled-model", "1")
}

func TestChannelGroupUpdatePreservesAbilityTagWhenSelectionIsOmitted(t *testing.T) {
	truncateTables(t)

	channel := Channel{
		Type:             1,
		Key:              "local-test-key",
		Status:           common.ChannelStatusEnabled,
		Name:             "group update",
		Models:           "enabled-model",
		Group:            "before-group",
		TagEnabledModels: []string{"enabled-model"},
		Priority:         common.GetPointer[int64](0),
		Weight:           common.GetPointer[uint](0),
	}
	require.NoError(t, channel.Insert())

	channel.Group = "after-group"
	channel.TagEnabledModels = nil
	require.NoError(t, channel.Update())

	assertStoredAbilityTag(t, channel.Id, "enabled-model", "1")
}

func TestBatchGroupUpdatePreservesAbilityTag(t *testing.T) {
	truncateTables(t)

	channelTag := "batch-group-update"
	channel := Channel{
		Type:             1,
		Key:              "local-test-key",
		Status:           common.ChannelStatusEnabled,
		Name:             "batch group update",
		Models:           "enabled-model",
		Group:            "before-group",
		Tag:              &channelTag,
		TagEnabledModels: []string{"enabled-model"},
		Priority:         common.GetPointer[int64](0),
		Weight:           common.GetPointer[uint](0),
	}
	require.NoError(t, channel.Insert())

	afterGroup := "after-group"
	require.NoError(t, EditChannelByTag(
		channelTag,
		nil,
		nil,
		nil,
		&afterGroup,
		nil,
		nil,
		nil,
		nil,
	))

	assertStoredAbilityTag(t, channel.Id, "enabled-model", "1")
}

func assertStoredAbilityTag(t *testing.T, channelID int, model string, expected string) {
	t.Helper()
	var ability Ability
	require.NoError(t, DB.Where("channel_id = ? AND model = ?", channelID, model).First(&ability).Error)
	require.NotNil(t, ability.Tag)
	require.Equal(t, expected, *ability.Tag)
}

func TestChannelTagEnabledModelsMySQL(t *testing.T) {
	dsn := os.Getenv("TEST_MYSQL_DSN")
	if dsn == "" {
		t.Skip("set TEST_MYSQL_DSN to run the MySQL ability tag integration test")
	}

	mysqlDB, err := gorm.Open(mysql.Open(dsn), &gorm.Config{})
	require.NoError(t, err)
	originalDB := DB
	DB = mysqlDB
	common.SetDatabaseTypes(common.DatabaseTypeMySQL, common.DatabaseTypeMySQL)
	t.Cleanup(func() {
		DB = originalDB
		common.SetDatabaseTypes(common.DatabaseTypeSQLite, common.DatabaseTypeSQLite)
	})

	testName := "ability-tag-mysql-" + time.Now().Format("20060102150405.000000000")
	t.Cleanup(func() {
		var channelIDs []int
		if err := mysqlDB.Model(&Channel{}).Where("name LIKE ?", testName+"%").Pluck("id", &channelIDs).Error; err != nil {
			t.Errorf("find temporary MySQL channels for cleanup: %v", err)
			return
		}
		if len(channelIDs) == 0 {
			return
		}
		if err := mysqlDB.Where("channel_id IN ?", channelIDs).Delete(&Ability{}).Error; err != nil {
			t.Errorf("delete temporary MySQL abilities: %v", err)
		}
		if err := mysqlDB.Where("id IN ?", channelIDs).Delete(&Channel{}).Error; err != nil {
			t.Errorf("delete temporary MySQL channels: %v", err)
		}
		var remainingAbilities int64
		if err := mysqlDB.Model(&Ability{}).Where("channel_id IN ?", channelIDs).Count(&remainingAbilities).Error; err != nil {
			t.Errorf("count temporary MySQL abilities after cleanup: %v", err)
		} else if remainingAbilities != 0 {
			t.Errorf("temporary MySQL abilities remain after cleanup: %d", remainingAbilities)
		}
		var remainingChannels int64
		if err := mysqlDB.Model(&Channel{}).Where("id IN ?", channelIDs).Count(&remainingChannels).Error; err != nil {
			t.Errorf("count temporary MySQL channels after cleanup: %v", err)
		} else if remainingChannels != 0 {
			t.Errorf("temporary MySQL channels remain after cleanup: %d", remainingChannels)
		}
	})

	channel := Channel{
		Type:             1,
		Key:              "mysql-integration-test-key",
		Status:           common.ChannelStatusEnabled,
		Name:             testName,
		Models:           "mysql-enabled-model,mysql-disabled-model",
		Group:            "default",
		TagEnabledModels: []string{},
		Priority:         common.GetPointer[int64](0),
		Weight:           common.GetPointer[uint](0),
	}
	require.NoError(t, channel.Insert())

	loadChannel := func() Channel {
		var stored Channel
		require.NoError(t, mysqlDB.First(&stored, channel.Id).Error)
		return stored
	}
	loadAbilities := func() map[string]Ability {
		var abilities []Ability
		require.NoError(t, mysqlDB.Where("channel_id = ?", channel.Id).Find(&abilities).Error)
		byModel := make(map[string]Ability, len(abilities))
		for _, ability := range abilities {
			byModel[ability.Model] = ability
		}
		return byModel
	}
	assertTag := func(abilities map[string]Ability, model string, expected *string) {
		ability, ok := abilities[model]
		require.True(t, ok, "missing ability for model %s", model)
		if expected == nil {
			require.Nil(t, ability.Tag, "model %s should have a NULL tag", model)
			return
		}
		require.NotNil(t, ability.Tag, "model %s should have a tag", model)
		require.Equal(t, *expected, *ability.Tag)
	}
	one := "1"

	// A new channel has no channel tag and no selected ability tags.
	require.Nil(t, loadChannel().Tag)
	abilities := loadAbilities()
	require.Len(t, abilities, 2)
	assertTag(abilities, "mysql-enabled-model", nil)
	assertTag(abilities, "mysql-disabled-model", nil)

	// Selecting one model marks only that ability with tag "1".
	channel.TagEnabledModels = []string{"mysql-enabled-model"}
	require.NoError(t, channel.Update())
	abilities = loadAbilities()
	assertTag(abilities, "mysql-enabled-model", &one)
	assertTag(abilities, "mysql-disabled-model", nil)

	// Removing the selection clears the ability tag back to SQL NULL.
	channel.TagEnabledModels = []string{}
	require.NoError(t, channel.Update())
	abilities = loadAbilities()
	assertTag(abilities, "mysql-enabled-model", nil)
	assertTag(abilities, "mysql-disabled-model", nil)

	// Re-enable the model before editing unrelated channel fields.
	channel.TagEnabledModels = []string{"mysql-enabled-model"}
	require.NoError(t, channel.Update())
	assertTag(loadAbilities(), "mysql-enabled-model", &one)

	updatedName := testName + "-updated"
	mapping := `{"mysql-client-model":"mysql-enabled-model"}`
	channel.Name = updatedName
	channel.Priority = common.GetPointer[int64](17)
	channel.Weight = common.GetPointer[uint](23)
	channel.Models = "mysql-enabled-model,mysql-disabled-model,mysql-new-model"
	channel.ModelMapping = &mapping
	channel.TagEnabledModels = []string{"mysql-enabled-model"}
	require.NoError(t, channel.Update())

	stored := loadChannel()
	require.Nil(t, stored.Tag)
	require.Equal(t, updatedName, stored.Name)
	require.EqualValues(t, 17, stored.GetPriority())
	require.EqualValues(t, 23, stored.GetWeight())
	require.Equal(t, channel.Models, stored.Models)
	require.Equal(t, mapping, stored.GetModelMapping())

	abilities = loadAbilities()
	require.Len(t, abilities, 3)
	assertTag(abilities, "mysql-enabled-model", &one)
	assertTag(abilities, "mysql-disabled-model", nil)
	assertTag(abilities, "mysql-new-model", nil)

	// A legacy/non-UI update that omits tag_enabled_models must preserve the tag.
	channel.Name = testName + "-legacy-update"
	channel.TagEnabledModels = nil
	require.NoError(t, channel.Update())
	abilities = loadAbilities()
	assertTag(abilities, "mysql-enabled-model", &one)
	assertTag(abilities, "mysql-disabled-model", nil)
	assertTag(abilities, "mysql-new-model", nil)
}
