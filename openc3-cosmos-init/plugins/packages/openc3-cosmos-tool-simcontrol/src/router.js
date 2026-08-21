/*
###############################################################################
# Copyright (c) ATTX, Inc. 2026. All Rights Reserved.
#
# This software and associated documentation (the "Software") are the
# proprietary and confidential information of ATTX, Inc. The Software is
# furnished under a license agreement between ATTX and the user organization
# and may be used or copied only in accordance with the terms of the agreement.
# Refer to 'license/attx_license.adoc' for standard license terms.
#
# EXPORT CONTROL NOTICE: THIS SOFTWARE MAY INCLUDE CONTENT CONTROLLED UNDER THE
# INTERNATIONAL TRAFFIC IN ARMS REGULATIONS (ITAR) OR THE EXPORT ADMINISTRATION
# REGULATIONS (EAR99). No part of the Software may be used, reproduced, or
# transmitted in any form or by any means, for any purpose, without the express
# written permission of ATTX, Inc.
###############################################################################
*/

/*
# Copyright 2026, OpenC3, Inc.
# All Rights Reserved.
#
# This program is free software; you can modify and/or redistribute it
# under the terms of the GNU Affero General Public License
# as published by the Free Software Foundation; version 3 with
# attribution addendums as found in the LICENSE.txt
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# This file may also be used under the terms of a commercial license
# if purchased from OpenC3, Inc.
*/

import { createRouter, createWebHistory } from 'vue-router'
import { prependBasePath } from '@openc3/js-common/utils'
import { NotFound } from '@openc3/vue-common/components'

const routes = [
  {
    path: '/',
    name: 'SimControl',
    component: () => import('./tools/SimControl/SimControl.vue'),
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: NotFound,
  },
]
routes.forEach(prependBasePath)

export default createRouter({
  history: createWebHistory(),
  routes,
})
