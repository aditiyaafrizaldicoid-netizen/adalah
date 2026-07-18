package config

import (
	"github.com/go-playground/locales/id"
	ut "github.com/go-playground/universal-translator"
	"github.com/go-playground/validator/v10"
	id_translations "github.com/go-playground/validator/v10/translations/id"
)

// NewValidator initializes playground validator with Indonesian translations
func NewValidator() (*validator.Validate, ut.Translator) {
	v := validator.New()

	idLocale := id.New()
	uni := ut.New(idLocale, idLocale)
	trans, _ := uni.GetTranslator("id")

	// Register Indonesian translations
	id_translations.RegisterDefaultTranslations(v, trans)

	return v, trans
}

